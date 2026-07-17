from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path

from .jra_history_dataset import FEATURE_NAMES, build_live_feature_records
from .jra_recent_form_dataset import (
    RECENT_FORM_SCHEMA, append_recent_form_live_features,
)


MODEL_VERSION = "jra-history-logistic-v1"
RECENT_FORM_MODEL_VERSION = "jra-history-logistic-recent-form-v2"


def train_history_models(
    records: list[dict], validation_fraction: float = 0.2, *,
    feature_names: list[str] | None = None, model_version: str = MODEL_VERSION,
) -> tuple[dict, dict]:
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:  # pragma: no cover - exercised by the CLI environment
        raise RuntimeError("scikit-learn is required; run with the ml optional dependency") from exc

    feature_names = list(feature_names or FEATURE_NAMES)
    dates = sorted({record["race_date"] for record in records})
    if len(dates) < 10:
        raise ValueError("at least 10 race dates are required")
    validation_days = max(1, round(len(dates) * validation_fraction))
    cutoff = dates[-validation_days]
    train = [record for record in records if record["race_date"] < cutoff]
    validation = [record for record in records if record["race_date"] >= cutoff]
    if not train or not validation:
        raise ValueError("time split produced an empty partition")

    x_train = [record["features"] for record in train]
    x_validation = [record["features"] for record in validation]
    scaler = StandardScaler().fit(x_train)
    x_train_scaled = scaler.transform(x_train)
    x_validation_scaled = scaler.transform(x_validation)
    validation_models = {}
    validation_probabilities = {}
    metrics = {}
    for target in ("win", "top3"):
        label = f"label_{target}"
        y_train = [record[label] for record in train]
        y_validation = [record[label] for record in validation]
        model = LogisticRegression(max_iter=1000, solver="lbfgs").fit(x_train_scaled, y_train)
        probabilities = model.predict_proba(x_validation_scaled)[:, 1].tolist()
        validation_models[target] = model
        validation_probabilities[target] = probabilities
        metrics[target] = {
            "brier": round(float(brier_score_loss(y_validation, probabilities)), 6),
            "log_loss": round(float(log_loss(y_validation, probabilities)), 6),
            "roc_auc": round(float(roc_auc_score(y_validation, probabilities)), 6),
            "positive_rate": round(sum(y_validation) / len(y_validation), 6),
        }

    race_metrics = _race_metrics(validation, validation_probabilities)
    report = {
        "model_version": model_version,
        "split": {
            "method": "race_date_chronological_holdout",
            "cutoff_date": cutoff,
            "train_dates": len({record["race_date"] for record in train}),
            "validation_dates": len({record["race_date"] for record in validation}),
            "train_races": len({record["race_id"] for record in train}),
            "validation_races": len({record["race_id"] for record in validation}),
            "train_runner_rows": len(train),
            "validation_runner_rows": len(validation),
        },
        "runner_metrics": metrics,
        "race_metrics": race_metrics,
        "hyperparameters": {"algorithm": "LogisticRegression", "solver": "lbfgs", "max_iter": 1000},
        "odds_used": False,
    }

    # Refit the released artifact on all historical rows after the untouched holdout report is fixed.
    x_all = [record["features"] for record in records]
    final_scaler = StandardScaler().fit(x_all)
    x_all_scaled = final_scaler.transform(x_all)
    artifact_models = {}
    for target in ("win", "top3"):
        model = LogisticRegression(max_iter=1000, solver="lbfgs").fit(
            x_all_scaled, [record[f"label_{target}"] for record in records]
        )
        artifact_models[target] = {
            "intercept": float(model.intercept_[0]),
            "coefficients": [float(value) for value in model.coef_[0]],
        }
    artifact = {
        "model_version": model_version,
        "created_at": datetime.now(UTC).isoformat(),
        "trained_through": max(record["race_date"] for record in records),
        "training_races": len({record["race_id"] for record in records}),
        "training_runner_rows": len(records),
        "feature_names": feature_names,
        "scaler": {
            "mean": [float(value) for value in final_scaler.mean_],
            "scale": [float(value) for value in final_scaler.scale_],
        },
        "models": artifact_models,
        "odds_used": False,
        "intended_use": "rank runners by win_probability and top3_probability; betting EV is out of scope",
    }
    artifact["artifact_hash"] = _artifact_hash(artifact)
    report["released_artifact_hash"] = artifact["artifact_hash"]
    report["coefficient_summary"] = {
        target: _coefficient_summary(artifact_models[target]["coefficients"], feature_names)
        for target in ("win", "top3")
    }
    return artifact, report


def predict_with_artifact(artifact: dict, features: list[float]) -> dict[str, float]:
    if len(features) != len(artifact["feature_names"]):
        raise ValueError("feature length does not match artifact")
    means = artifact["scaler"]["mean"]
    scales = artifact["scaler"]["scale"]
    scaled = [(value - mean) / (scale or 1.0) for value, mean, scale in zip(features, means, scales)]
    result = {}
    for target, model in artifact["models"].items():
        logit = model["intercept"] + sum(coef * value for coef, value in zip(model["coefficients"], scaled))
        result[f"{target}_probability"] = 1.0 / (1.0 + math.exp(-max(min(logit, 35), -35)))
    return result


def load_model_artifact(path: str | Path) -> dict:
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise FileNotFoundError(f"history model artifact not found: {artifact_path}")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if artifact.get("feature_names") not in (FEATURE_NAMES, RECENT_FORM_SCHEMA):
        raise ValueError("history model feature schema does not match this application")
    return artifact


def score_live_records(artifact: dict, records: list[dict]) -> list[dict]:
    scored = []
    raw_win_total = 0.0
    for record in records:
        probabilities = predict_with_artifact(artifact, record["features"])
        raw_win_total += probabilities["win_probability"]
        scored.append({
            **record,
            **probabilities,
            "explanation": explain_with_artifact(artifact, record["features"], target="top3"),
        })
    for item in scored:
        item["win_probability_race_normalized"] = (
            item["win_probability"] / raw_win_total if raw_win_total else 0.0
        )
    return sorted(
        scored,
        key=lambda item: (-item["top3_probability"], -item["win_probability_race_normalized"], item["horse_no"]),
    )


def build_artifact_live_records(artifact: dict, db_path: str | Path, *, target_date, course, card) -> list[dict]:
    records = build_live_feature_records(db_path, target_date=target_date, course=course, card=card)
    if artifact["feature_names"] == FEATURE_NAMES:
        return records
    if artifact["feature_names"] == RECENT_FORM_SCHEMA:
        return append_recent_form_live_features(records, db_path, target_date=target_date)
    raise ValueError("history model feature schema does not match this application")


def explain_with_artifact(artifact: dict, features: list[float], *, target: str, limit: int = 3) -> dict:
    if target not in artifact["models"]:
        raise ValueError(f"unknown model target={target}")
    model = artifact["models"][target]
    terms = []
    for name, value, mean, scale, coefficient in zip(
        artifact["feature_names"], features, artifact["scaler"]["mean"],
        artifact["scaler"]["scale"], model["coefficients"],
    ):
        standardized = (value - mean) / (scale or 1.0)
        terms.append({
            "feature": name,
            "value": round(value, 6),
            "contribution": round(standardized * coefficient, 6),
        })
    positives = sorted((term for term in terms if term["contribution"] > 0), key=lambda item: item["contribution"], reverse=True)[:limit]
    negatives = sorted((term for term in terms if term["contribution"] < 0), key=lambda item: item["contribution"])[:limit]
    return {
        "target": target,
        "intercept": round(model["intercept"], 6),
        "positive_contributions": positives,
        "negative_contributions": negatives,
    }


def write_model_artifacts(artifact: dict, report: dict, output_dir: str | Path) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (path / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _race_metrics(records: list[dict], probabilities: dict[str, list[float]]) -> dict:
    grouped: dict[str, list[tuple[dict, float, float]]] = defaultdict(list)
    for record, win, top3 in zip(records, probabilities["win"], probabilities["top3"]):
        grouped[record["race_id"]].append((record, win, top3))
    winner_hits = 0
    axis_top3_hits = 0
    top3_recall_sum = 0.0
    for runners in grouped.values():
        win_pick = max(runners, key=lambda item: item[1])[0]
        axis = max(runners, key=lambda item: item[2])[0]
        predicted_top3 = sorted(runners, key=lambda item: item[2], reverse=True)[:3]
        winner_hits += win_pick["label_win"]
        axis_top3_hits += axis["label_top3"]
        top3_recall_sum += sum(item[0]["label_top3"] for item in predicted_top3) / 3
    count = len(grouped)
    return {
        "races": count,
        "top1_winner_rate": round(winner_hits / count, 6),
        "axis_top3_rate": round(axis_top3_hits / count, 6),
        "predicted_top3_recall": round(top3_recall_sum / count, 6),
    }


def _coefficient_summary(coefficients: list[float], feature_names: list[str], limit: int = 10) -> list[dict]:
    pairs = sorted(zip(feature_names, coefficients), key=lambda item: abs(item[1]), reverse=True)[:limit]
    return [{"feature": name, "coefficient": round(value, 6)} for name, value in pairs]


def _artifact_hash(artifact: dict) -> str:
    payload = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
