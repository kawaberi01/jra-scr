"""概要: 予想家由来S08の通過順・ラップ・上がり特徴を種類別に除外して比較する。
作成日: 2026-10-17
入力: spec120、固定SQL31/34、step4の保存モデルと入力証跡。
出力: 新規runのモデル・欠測診断・選択ペア予測・レース別評価・集計。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_ablation.py
注意事項: SELECT専用。既使用期間の探索研究。旧入力・元データ複製・削除・運用変更なし。
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import traceback
from unittest.mock import patch

import joblib
import numpy as np
from scipy.special import softmax
from sklearn.impute import SimpleImputer
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts
from .jra_research_contracts import ResearchError, digest
from .jra_research_resources import check_memory
from . import jra_research_tipster as content_source
from . import jra_research_tipster_experiment as step4
from . import jra_research_tipster_smoke as base


REFERENCE = "20261017T051954Z_72e96ea8375744bcac0243ab86518cca"
REFERENCE_PATH = ROOT / "artifacts/jra_research/runs" / REFERENCE
VARIANTS = ("history", "full", "no_corner", "no_pace", "no_closing")
CONFIG = {**step4.CONFIG, "protocol": "spec120-content-ablation-v1", "variants": list(VARIANTS),
          "reference_run": REFERENCE, "gate": "fixed_reference_full", "bootstrap_days": 1000,
          "rich_pair_fraction": .5, "prediction_output": "chosen_pairs_only"}


def raw_diagnostics(rows, legacy):
    """SQL内容行の原値・解析適格・同定可能率を月別に集計し、原行は保存しない。"""
    monthly = defaultdict(Counter)
    fields = Counter(row["netkeiba_race_id"] for row in rows if (legacy.v2.previous.number(row["rank"]) or 0) >= 1)
    for row in rows:
        count = monthly[row["race_date"][:7]]
        count["runner_rows"] += 1
        count["identity_resolved"] += int(legacy.v2.previous.identity(row["horse_name"], row["sex_age"], row["race_date"]) is not None)
        count["corner_nonempty"] += int(bool(str(row.get("corner_order") or "").strip()))
        count["corner_numeric"] += int(bool(re.findall(r"\d+", str(row.get("corner_order") or ""))))
        positions = re.findall(r"\d+", str(row.get("corner_order") or ""))
        count["corner_eligible"] += int(bool(positions and 1 <= int(positions[-1]) <= fields[row["netkeiba_race_id"]]))
        count["closing_numeric"] += int(legacy.v2.previous.number(row.get("final_3f")) is not None)
        length = int("".join(re.findall(r"\d", str(row.get("distance")))) or 0)
        try:
            laps = [float(x) for x in json.loads(row.get("race_laps_json") or "[]")]
            count["lap_nonempty"] += int(bool(laps))
            count["lap_format_eligible"] += int(length % 200 == 0 and len(laps) == length // 200 and len(laps) >= 6 and all(8 < x < 20 for x in laps))
        except (TypeError, ValueError):
            count["lap_parse_failed"] += 1
    return {month: dict(values) for month, values in sorted(monthly.items())}


def feature_names(legacy):
    """既存ペア設計の実装順と一致する120列の名前を組み立てる。"""
    history = legacy.v2.previous.HISTORY_KEYS
    content = legacy.v2.previous.CONTENT_NAMES
    condition = legacy.v2.previous.CONDITION_NAMES
    return ([f"market_{i}" for i in range(7)] + [f"history_{op}_{name}" for op in ("sum", "difference") for name in history]
            + [f"content_{op}_{name}" for op in ("sum", "difference") for name in content]
            + [f"condition_{op}_{name}" for op in ("sum", "difference") for name in condition]
            + ["both_front", "front_difference", "both_front_x_front_density"])


def removed_columns(legacy):
    """直接項目と依存する派生項目を含め、事前固定した除外列を返す。"""
    start = legacy.CONTENT_START
    n = len(legacy.v2.previous.CONTENT_NAMES)
    m = len(legacy.v2.previous.CONDITION_NAMES)
    corner = {start + offset + i for offset in (0, n) for i in (7, 8, 9, 11)}
    corner |= {start + 2 * n + offset + i for offset in (0, m) for i in (23, 24)}
    corner |= set(range(start + 2 * n + 2 * m, start + 2 * n + 2 * m + 3))
    return {"no_corner": corner,
            "no_pace": {start + offset + i for offset in (0, n) for i in (10, 11)},
            "no_closing": {start + offset + i for offset in (0, n) for i in (5, 6)}}


def gate(record, transform, legacy):
    """基準S08の混合重みを再現し、除外案でも同じ値を使う。"""
    c, start = record["full_x"], legacy.CONTENT_START
    past = np.clip((c[:, start] - c[:, start + 13]) / 2, 0, 1)
    columns = transform["keep"][transform["keep"] >= start]
    available = np.isfinite(c[:, columns]).mean(axis=1) if len(columns) else np.zeros(len(c))
    h = (record["history_x"][:, 7] - record["history_x"][:, 7 + legacy.H]) / 2
    return past * available, (h > 0).astype(float)


def fit_ablation(name, removed, recent, calibration, reference_transform, legacy):
    """該当列とその欠測indicatorを除外して内容モデルだけを再学習する。"""
    keep = np.asarray([i for i in reference_transform["keep"] if i not in removed], dtype=int)
    imputer = SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
    imputer.fit(np.concatenate([r["full_x"][:, keep] for r in recent]))
    try:
        for record in recent + calibration:
            record["ablation_x"] = imputer.transform(record["full_x"][:, keep])
        fitted = legacy.fit_q(recent, calibration, "ablation_x")
    finally:
        for record in recent + calibration:
            record.pop("ablation_x", None)
    check_memory(2147483648)
    print(json.dumps({"stage": "trained_ablation", "variant": name, "kept": len(keep), "alpha": fitted["alpha"]}), flush=True)
    return {"model": fitted, "transform": {"keep": keep, "imputer": imputer}}


def predict(record, reference, alternatives, legacy):
    """結果・払戻を除いた設計と保存モデルだけから5案の馬連確率を計算する。"""
    values = legacy.scores(record, reference["models"], reference["transforms"])
    out = {"history": values["q_history"], "full": values["q_gated"]}
    weights, has_history = gate(record, reference["transforms"]["recent_x"], legacy)
    market = record["market"]
    delta_history = np.log(out["history"] / market)
    for name, value in alternatives.items():
        transform, fitted = value["transform"], value["model"]
        model = fitted["model"]
        x = transform["imputer"].transform(record["full_x"][:, transform["keep"]])
        q_recent = softmax(np.log(market) + fitted["alpha"] * ((x / model["scale"]) @ model["coef"]))
        out[name] = softmax(np.log(market) + has_history * ((1 - weights) * delta_history + weights * np.log(q_recent / market)))
    return out


def bootstrap(rows, name):
    """同日をまとめて再標本化し、fullとの差のレース平均損失区間を返す。"""
    groups = defaultdict(list)
    for row in rows:
        groups[row["race_date"]].append(row["logloss"][name] - row["logloss"]["full"])
    daily = np.asarray([(sum(v), len(v)) for _, v in sorted(groups.items())])
    rng = np.random.default_rng(CONFIG["seed"])
    totals = daily[rng.integers(0, len(daily), size=(CONFIG["bootstrap_days"], len(daily)))].sum(axis=1)
    return {"mean_loss_difference": float(daily[:, 0].sum() / daily[:, 1].sum()),
            "day_bootstrap_95": np.quantile(totals[:, 0] / totals[:, 1], [.025, .975]).tolist(),
            "days": len(daily), "negative_favors_variant": True}


def evaluate(artifacts, records, coverage, diagnostic, legacy, reference_bundle, baseline):
    """固定5案を比較し、基準再現・保存推論・会計を確認して結果を保存する。"""
    reference = reference_bundle["families"]["long"]
    recent = [r for r in records if r["period"] == "train" and r["race_date"] >= CONFIG["recent_from"]]
    calibration = [r for r in records if r["period"] == "calibration"]
    evaluated = sorted((r for r in records if r["period"].startswith("evaluation")), key=lambda r: (r["race_date"], r["race_id"]))
    names, removed = feature_names(legacy), removed_columns(legacy)
    if any(len(r["full_x"][0]) != len(names) for r in recent + calibration + evaluated):
        raise ResearchError("ablation_feature_contract_changed", 4)
    alternatives = {name: fit_ablation(name, columns, recent, calibration, reference["transforms"]["recent_x"], legacy) for name, columns in removed.items()}
    model_path = artifacts.path / "models.joblib"
    joblib.dump({"reference_run": REFERENCE, "reference_model_sha256": baseline["model_sha256"], "alternatives": alternatives, "config": CONFIG}, model_path)
    reloaded = joblib.load(model_path)["alternatives"]
    per_race, tickets = [], defaultdict(list)
    reload_checks = 0

    def selected_predictions():
        """選んだペアだけを保存し、全ペア予測の重複保存を避ける。"""
        nonlocal reload_checks
        for record in evaluated:
            allowed = {k: v for k, v in record.items() if k not in {"target", "wide_target", "q_payout", "w_payout"}}
            scores = predict(allowed, reference, alternatives, legacy)
            again = predict(allowed, reference, reloaded, legacy)
            if not all(np.array_equal(scores[k], again[k]) for k in scores):
                raise ResearchError("saved_model_prediction_changed", 5)
            reload_checks += 1
            start = legacy.CONTENT_START
            corner = float(np.isfinite(record["full_x"][:, start + 9]).mean())
            pace = float(np.isfinite(record["full_x"][:, start + 10]).mean())
            row = {"race_key": record["race_id"], "race_date": record["race_date"], "period": record["period"],
                   "stratum": "rich" if corner >= .5 and pace >= .5 else "sparse",
                   "corner_pair_observed": corner, "pace_pair_observed": pace,
                   "logloss": {}, "brier": {}, "tickets": {}}
            for name, probability in scores.items():
                if not np.isfinite(probability).all() or not np.isclose(probability.sum(), 1):
                    raise ResearchError("invalid_ablation_probability", 5)
                row["logloss"][name] = float(-record["target"] @ np.log(np.maximum(probability, 1e-15)))
                row["brier"][name] = float(np.mean((probability - record["target"]) ** 2))
                _, indices = legacy.choose("S08", {"q_gated": probability}, allowed)
                if len(indices) > 1:
                    raise ResearchError("ablation_ticket_limit", 5)
                row["tickets"][name] = []
                for index in indices:
                    pair = record["keys"][index]
                    ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": record["q_payout"].get(pair, 0) * 6}
                    saved = {**ticket, "race_key": record["race_id"], "race_date": record["race_date"], "period": record["period"]}
                    tickets[name].append(saved)
                    row["tickets"][name].append({**ticket, "horses": list(pair)})
                    yield {"race_key": record["race_id"], "race_date": record["race_date"], "venue": record["course"],
                           "variant": name, "split": record["period"], "horses": list(pair), "probability": float(probability[index]),
                           "target": int(record["target"][index]), "ticket": ticket}
            per_race.append(row)
            check_memory(2147483648)

    prediction_hash = artifacts.write_predictions(selected_predictions())
    periods = ("evaluation_2025", "evaluation_early", "evaluation_late", "all")
    results, comparisons = {}, {}
    for name in VARIANTS:
        results[name] = {}
        comparisons[name] = {}
        for part in periods:
            rows = [r for r in per_race if part == "all" or r["period"] == part]
            actual_tickets = [t for t in tickets[name] if part == "all" or t["period"] == part]
            results[name][part] = {**step4.summary(actual_tickets),
                                   "logloss": float(np.mean([r["logloss"][name] for r in rows])),
                                   "brier": float(np.mean([r["brier"][name] for r in rows]))}
            comparisons[name][part] = bootstrap(rows, name)
    for name, original in (("history", "long_S08_history"), ("full", "long_S08")):
        actual = results[name]["all"]
        expected = baseline["results"][original]["all"]
        quality_name = "long/q_history" if name == "history" else "long/q_gated"
        expected_loss = next(q["value"] for q in baseline["quality"] if q["model"] == quality_name and q["period"] == "all" and q["metric"] == "logloss")
        if any(actual[k] != expected[k] for k in ("races", "stake_yen", "payout_yen")) or not np.isclose(actual["logloss"], expected_loss, atol=1e-12, rtol=0):
            raise ResearchError("reference_reproduction_changed", 5, variant=name)
    strata = {}
    for group in ("rich", "sparse"):
        rows = [r for r in per_race if r["stratum"] == group]
        strata[group] = {"races": len(rows), "models": {name: {"logloss": float(np.mean([r["logloss"][name] for r in rows])),
                           "vs_full": bootstrap(rows, name)} for name in VARIANTS}} if rows else {"races": 0}
    metrics = {"status": "passed", "stage": "tipster_content_ablation", "input_digest": coverage["input_digest"],
               "reference_run": REFERENCE, "reference_reproduced": True, "live_adopted": False,
               "unseen_test": False, "sqlite_used": False, "input_guard_enforced": True,
               "counts": coverage["adopted_by_split"], "recent_training_races": len(recent),
               "feature_names": names, "removed_features": {k: [names[i] for i in sorted(v)] for k, v in removed.items()},
               "kept_columns": {k: v["transform"]["keep"].tolist() for k, v in alternatives.items()},
               "calibration_alpha": {k: v["model"]["alpha"] for k, v in alternatives.items()},
               "raw_sql_monthly": diagnostic, "results": results, "paired_loss_comparisons": comparisons,
               "observed_strata": strata, "race_diagnostics": per_race, "reload_score_checks": reload_checks,
               "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}
    artifacts.write_json("metrics.json", metrics)
    artifacts.finish(overall_complete=False, stage=metrics["stage"], content_ablation_complete=True,
                     predictions_sha256=prediction_hash, metrics_sha256=digest(metrics))
    return {"run_id": artifacts.run_id, "status": "complete", "results": {k: v["all"] for k, v in results.items()}}


def execute_ablation():
    """入力拒否ガード下でSQL診断・固定比較を行い、失敗時は証跡を保存する。"""
    base.install_input_guard()
    artifacts = RunArtifacts(CONFIG, "tipster-content-ablation")
    print(json.dumps({"run_id": artifacts.run_id, "stage": "starting"}), flush=True)
    try:
        baseline = json.loads((REFERENCE_PATH / "metrics.json").read_text(encoding="utf-8"))
        model_path = REFERENCE_PATH / "models.joblib"
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != baseline["model_sha256"]:
            raise ResearchError("reference_model_changed", 3)
        reference_bundle = joblib.load(model_path)
        legacy = base.load_legacy()
        diagnostic = {}
        read = content_source.read_tipster_history

        def audited_read(*args, **kwargs):
            """既存SQL読取に月別診断だけを付加し、同じ入力を返す。"""
            raw, wide, audit = read(*args, **kwargs)
            diagnostic.update(raw_diagnostics(raw, legacy))
            return raw, wide, audit

        with patch.object(content_source, "read_tipster_history", audited_read):
            records, coverage = step4.prepare(artifacts, legacy)
        if coverage["input_digest"] != baseline["input_digest"] or coverage["adopted_by_split"] != baseline["adopted_by_split"]:
            raise ResearchError("ablation_input_changed", 4)
        with threadpool_limits(limits=1):
            return evaluate(artifacts, records, coverage, diagnostic, legacy, reference_bundle, baseline)
    except ResearchError as error:
        artifacts.fail(error)
        raise
    except Exception as error:
        frames = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(error.__traceback__)]
        failure = ResearchError("tipster_ablation_failed", 4, error_type=type(error).__name__, frames=frames)
        artifacts.fail(failure)
        raise failure from None
