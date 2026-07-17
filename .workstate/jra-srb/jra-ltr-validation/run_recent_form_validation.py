from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import UTC, datetime
import json
from pathlib import Path

from catboost import CatBoostRanker, Pool
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from jra_srb.jra_history_dataset import FEATURE_NAMES, build_history_dataset


DB = Path("data/db/analysis.sqlite")
OUTPUT = Path(".workstate/jra-srb/jra-ltr-validation/recent-form-v1")
RECENT_FEATURE_NAMES = [
    "form_history_count_scaled",
    "form_last_finish_strength",
    "form_recent3_finish_strength",
    "form_recent5_finish_strength",
    "form_recent3_top3_rate",
    "form_recent3_vs_career_strength",
]


def append_recent_form_features(records: list[dict]) -> list[dict]:
    by_race: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_race[record["race_id"]].append(record)
    history: dict[str, deque[tuple[float, int]]] = defaultdict(lambda: deque(maxlen=5))
    career_strength_index = FEATURE_NAMES.index("horse_finish_strength")
    output = []
    for race_id, runners in sorted(
        by_race.items(), key=lambda item: (item[1][0]["race_date"], item[0])
    ):
        field_size = len(runners)
        for record in runners:
            recent = history[record["horse_name"]]
            last_strength = recent[-1][0] if recent else 0.5
            recent3 = list(recent)[-3:]
            recent3_strength = _mean([item[0] for item in recent3], 0.5)
            recent5_strength = _mean([item[0] for item in recent], 0.5)
            recent3_top3 = _mean([float(item[1]) for item in recent3], 0.25)
            career_strength = float(record["features"][career_strength_index])
            features = [
                min(len(recent), 5) / 5,
                last_strength,
                recent3_strength,
                recent5_strength,
                recent3_top3,
                recent3_strength - career_strength if recent else 0.0,
            ]
            output.append({**record, "features": [*record["features"], *features]})
        for record in runners:
            rank = int(record["actual_rank"])
            strength = 1.0 - (rank - 1) / max(field_size - 1, 1)
            history[record["horse_name"]].append((strength, int(rank <= 3)))
    return output


def split_dates(records: list[dict]) -> dict[str, set[str]]:
    dates = sorted({record["race_date"] for record in records})
    first = len(dates) * 70 // 100
    second = len(dates) * 85 // 100
    return {
        "train": set(dates[:first]),
        "calibration": set(dates[first:second]),
        "external": set(dates[second:]),
    }


def relevance(record: dict) -> int:
    return max(0, 4 - int(record["actual_rank"]))


def evaluate(records: list[dict], scores: list[float]) -> dict:
    grouped: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for record, score in zip(records, scores):
        grouped[record["race_id"]].append((record, float(score)))
    winner_hits = 0
    axis_top3_hits = 0
    top3_recall = 0.0
    mean_rank = 0.0
    for runners in grouped.values():
        ranked = sorted(runners, key=lambda item: (-item[1], int(item[0]["horse_no"])))
        winner_hits += ranked[0][0]["label_win"]
        axis_top3_hits += ranked[0][0]["label_top3"]
        top3_recall += sum(item[0]["label_top3"] for item in ranked[:3]) / 3
        mean_rank += ranked[0][0]["actual_rank"]
    count = len(grouped)
    return {
        "races": count,
        "top1_winner_rate": winner_hits / count,
        "axis_top3_rate": axis_top3_hits / count,
        "predicted_top3_recall": top3_recall / count,
        "mean_axis_actual_rank": mean_rank / count,
    }


def fit_and_evaluate(records: list[dict], dates: dict[str, set[str]]) -> dict:
    train = [record for record in records if record["race_date"] in dates["train"]]
    calibration = [record for record in records if record["race_date"] in dates["calibration"]]
    external = [record for record in records if record["race_date"] in dates["external"]]
    train_pool = Pool(
        [record["features"] for record in train],
        label=[relevance(record) for record in train],
        group_id=[record["race_id"] for record in train],
    )
    model = CatBoostRanker(
        loss_function="YetiRank",
        iterations=400,
        depth=6,
        learning_rate=0.05,
        l2_leaf_reg=8.0,
        random_seed=20260717,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(train_pool)
    return {
        "calibration": evaluate(
            calibration,
            model.predict(Pool(
                [record["features"] for record in calibration],
                group_id=[record["race_id"] for record in calibration],
            )),
        ),
        "external": evaluate(
            external,
            model.predict(Pool(
                [record["features"] for record in external],
                group_id=[record["race_id"] for record in external],
            )),
        ),
    }


def fit_logistic_and_evaluate(records: list[dict], dates: dict[str, set[str]]) -> dict:
    train = [record for record in records if record["race_date"] in dates["train"]]
    calibration = [record for record in records if record["race_date"] in dates["calibration"]]
    external = [record for record in records if record["race_date"] in dates["external"]]
    scaler = StandardScaler().fit([record["features"] for record in train])
    model = LogisticRegression(max_iter=1000, solver="lbfgs").fit(
        scaler.transform([record["features"] for record in train]),
        [record["label_top3"] for record in train],
    )

    def scores(rows: list[dict]) -> list[float]:
        return model.predict_proba(scaler.transform([record["features"] for record in rows]))[:, 1]

    return {
        "calibration": evaluate(calibration, scores(calibration)),
        "external": evaluate(external, scores(external)),
    }


def logistic_score_splits(records: list[dict], dates: dict[str, set[str]]) -> dict[str, list[tuple[dict, float]]]:
    train = [record for record in records if record["race_date"] in dates["train"]]
    scaler = StandardScaler().fit([record["features"] for record in train])
    model = LogisticRegression(max_iter=1000, solver="lbfgs").fit(
        scaler.transform([record["features"] for record in train]),
        [record["label_top3"] for record in train],
    )
    output = {}
    for split in ("calibration", "external"):
        rows = [record for record in records if record["race_date"] in dates[split]]
        probabilities = model.predict_proba(scaler.transform([record["features"] for record in rows]))[:, 1]
        output[split] = list(zip(rows, (float(value) for value in probabilities)))
    return output


def gate_trials(
    baseline_rows: list[tuple[dict, float]], enhanced_rows: list[tuple[dict, float]],
) -> dict[str, dict]:
    baseline = _axis_by_race(baseline_rows)
    enhanced = _axis_by_race(enhanced_rows)
    grouped_enhanced: dict[str, list[dict]] = defaultdict(list)
    for record, _ in enhanced_rows:
        grouped_enhanced[record["race_id"]].append(record)
    rules = (
        "always_enhanced", "axis_starts_1", "axis_starts_2", "axis_starts_3", "axis_starts_5",
        "field_coverage_50", "field_coverage_75", "axis_recent3_strength_50", "axis_recent3_strength_60",
    )
    return {
        rule: _axis_metrics([
            enhanced[race_id] if _gate_allows(rule, enhanced[race_id], grouped_enhanced[race_id]) else baseline[race_id]
            for race_id in baseline
        ])
        for rule in rules
    }


def _axis_by_race(rows: list[tuple[dict, float]]) -> dict[str, dict]:
    grouped: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for record, score in rows:
        grouped[record["race_id"]].append((record, score))
    return {
        race_id: max(items, key=lambda item: (item[1], -int(item[0]["horse_no"])))[0]
        for race_id, items in grouped.items()
    }


def _gate_allows(rule: str, axis: dict, runners: list[dict]) -> bool:
    offset = len(FEATURE_NAMES)
    starts = axis["features"][offset] * 5
    recent3_strength = axis["features"][offset + 2]
    if rule == "always_enhanced":
        return True
    if rule.startswith("axis_starts_"):
        return starts >= int(rule.rsplit("_", 1)[1])
    if rule.startswith("field_coverage_"):
        threshold = int(rule.rsplit("_", 1)[1]) / 100
        coverage = sum(record["features"][offset] > 0 for record in runners) / len(runners)
        return coverage >= threshold
    if rule == "axis_recent3_strength_50":
        return starts > 0 and recent3_strength >= 0.50
    if rule == "axis_recent3_strength_60":
        return starts > 0 and recent3_strength >= 0.60
    raise ValueError(f"unknown gate rule={rule}")


def _axis_metrics(records: list[dict]) -> dict:
    count = len(records)
    return {
        "races": count,
        "top1_winner_rate": sum(record["label_win"] for record in records) / count,
        "axis_top3_rate": sum(record["label_top3"] for record in records) / count,
        "mean_axis_actual_rank": sum(record["actual_rank"] for record in records) / count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline and recent-form JRA rankers.")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    baseline, metadata = build_history_dataset(args.db)
    enhanced = append_recent_form_features(baseline)
    dates = split_dates(baseline)
    baseline_result = fit_and_evaluate(baseline, dates)
    enhanced_result = fit_and_evaluate(enhanced, dates)
    logistic_baseline = fit_logistic_and_evaluate(baseline, dates)
    logistic_enhanced = fit_logistic_and_evaluate(enhanced, dates)
    baseline_scores = logistic_score_splits(baseline, dates)
    enhanced_scores = logistic_score_splits(enhanced, dates)
    calibration_gates = gate_trials(baseline_scores["calibration"], enhanced_scores["calibration"])
    enhanced_calibration = calibration_gates["always_enhanced"]
    viable_gates = {
        name: metrics for name, metrics in calibration_gates.items()
        if metrics["top1_winner_rate"] >= enhanced_calibration["top1_winner_rate"]
        and metrics["axis_top3_rate"] >= enhanced_calibration["axis_top3_rate"]
    }
    chosen_gate = max(
        viable_gates,
        key=lambda name: (
            viable_gates[name]["axis_top3_rate"], viable_gates[name]["top1_winner_rate"],
            -viable_gates[name]["mean_axis_actual_rank"], name == "always_enhanced",
        ),
    )
    external_gates = gate_trials(baseline_scores["external"], enhanced_scores["external"])
    gate_promoted = (
        external_gates[chosen_gate]["top1_winner_rate"] >= external_gates["always_enhanced"]["top1_winner_rate"]
        and external_gates[chosen_gate]["axis_top3_rate"] >= external_gates["always_enhanced"]["axis_top3_rate"]
        and chosen_gate != "always_enhanced"
    )
    baseline_external = baseline_result["external"]
    enhanced_external = enhanced_result["external"]
    result = {
        "theory": "recent_form_ranker_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": metadata,
        "date_ranges": {name: [min(values), max(values)] for name, values in dates.items()},
        "recent_feature_names": RECENT_FEATURE_NAMES,
        "baseline": baseline_result,
        "enhanced": enhanced_result,
        "logistic_baseline": logistic_baseline,
        "logistic_enhanced": logistic_enhanced,
        "external_delta": {
            key: enhanced_external[key] - baseline_external[key]
            for key in ("top1_winner_rate", "axis_top3_rate", "predicted_top3_recall", "mean_axis_actual_rank")
        },
        "promotion_rule": "Promote only when external winner rate and axis top3 rate do not decline, and at least one improves.",
        "promoted": (
            enhanced_external["top1_winner_rate"] >= baseline_external["top1_winner_rate"]
            and enhanced_external["axis_top3_rate"] >= baseline_external["axis_top3_rate"]
            and (
                enhanced_external["top1_winner_rate"] > baseline_external["top1_winner_rate"]
                or enhanced_external["axis_top3_rate"] > baseline_external["axis_top3_rate"]
            )
        ),
        "logistic_external_delta": {
            key: logistic_enhanced["external"][key] - logistic_baseline["external"][key]
            for key in ("top1_winner_rate", "axis_top3_rate", "predicted_top3_recall", "mean_axis_actual_rank")
        },
        "gate_validation": {
            "selection_data": "calibration only",
            "calibration_trials": calibration_gates,
            "chosen": chosen_gate,
            "external": external_gates[chosen_gate],
            "external_always_enhanced": external_gates["always_enhanced"],
            "promoted_beyond_v2": gate_promoted,
        },
        "warning": "Accuracy-only validation. Betting profitability is not evaluated.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "recent-form-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\r\n",
    )
    print(json.dumps(result, ensure_ascii=False))


def _mean(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else default


if __name__ == "__main__":
    main()
