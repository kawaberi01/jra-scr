"""概要: R1校正・価格研究の保存成果物をSQL再読取せず照合する。
作成日: 2026-10-18
入力: --run-idで指定する完了研究runと基準R1成果物。
出力: 同runのverification.jsonとprice-policy-comparison.json。
実行例: uv run --frozen --extra ml python scripts/verify_jra_r1_calibration.py --run-id <run-id>
注意事項: 再学習・SQL接続・実購入なし。既存予測/モデルを変更しない。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math

import joblib
import numpy as np

from jra_srb.jra_research_artifacts import ROOT, existing_run
from jra_srb.jra_research_contracts import canonical_json, digest
from jra_srb.jra_research_r1_live import BASELINE, read_json, require
from jra_srb.jra_research_r1_calibration import (
    CONFIG, PERIODS, POLICIES, VARIANTS, discounts, in_period, paired_interval,
)


def near(actual, expected, reason):
    """欠測と数値を区別し、丸め誤差だけを許容して照合する。"""
    if actual is None or expected is None:
        require(actual is expected, reason)
    else:
        require(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), reason)


def accounting(rows):
    """保存選択ペアだけから会計・払戻集中・最大資金減少を再計算する。"""
    stake = sum(r["ticket"]["stake_yen"] for r in rows)
    payout = sum(r["ticket"]["payout_yen"] for r in rows)
    largest = max((r["ticket"]["payout_yen"] for r in rows), default=0)
    balance = peak = drawdown = 0
    for r in sorted(rows, key=lambda x: (x["race_date"], x["race_key"])):
        balance += r["ticket"]["payout_yen"] - r["ticket"]["stake_yen"]
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    return {"races": len(rows), "days": len({r["race_date"] for r in rows}), "stake_yen": stake,
            "payout_yen": payout, "profit_yen": payout - stake, "return_rate": payout / stake if stake else None,
            "max_drawdown_yen": drawdown, "top_payout_share": largest / payout if payout else None,
            "return_rate_without_top_payout": (payout - largest) / stake if stake else None,
            "hits": sum(r["target"] for r in rows), "expected_hits": sum(r["probability"] for r in rows),
            "quoted_hit_payout_yen": sum(r["ticket"]["quoted_odds"] * 600 for r in rows if r["target"])}


def price_comparison(rows, variant, period):
    """同じ開催日の損益差を再標本化し、価格政策の比較を補助診断として返す。"""
    subset = [r for r in rows if in_period(r, period)]
    if not subset:
        return {"races": 0, "days": 0, "profit_delta_yen": None, "profit_delta_95": None}
    daily = defaultdict(float)
    for r in subset:
        profits = [r["payout"][variant + "_" + p] - r["stake"][variant + "_" + p] for p in POLICIES]
        daily[r["race_date"]] += profits[1] - profits[0]
    values = np.asarray([v for _, v in sorted(daily.items())])
    sampled = np.random.default_rng(181).integers(0, len(values), size=(2000, len(values)))
    totals = values[sampled].sum(axis=1)
    return {"races": len(subset), "days": len(values), "profit_delta_yen": float(values.sum()),
            "profit_delta_95": np.quantile(totals, [.025, .975]).tolist(), "replicates": 2000,
            "comparison": "P1_minus_P0_same_races_and_days", "not_policy_selection": True}


def write_once(path, value):
    """同一の再確認を許し、異なる既存証跡を上書きしない。"""
    if path.exists():
        require(digest(read_json(path)) == digest(value), "r1_existing_verification_differs")
    else:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def verify(run_id):
    """予測・会計・モデル・期間・選択・確率帯集計の保存整合を検証する。"""
    path = existing_run(run_id)
    metrics, manifest, config = (read_json(path / f) for f in ("metrics.json", "manifest.json", "config.json"))
    require(manifest["status"] == "complete" and metrics["status"] == "passed", "r1_calibration_run_incomplete")
    require(config["protocol"] == CONFIG["protocol"] and digest(metrics) == manifest["metrics_sha256"], "r1_calibration_metrics_hash")
    require(hashlib.sha256((path / "models.joblib").read_bytes()).hexdigest() == metrics["model_sha256"], "r1_calibration_model_hash")
    saved = joblib.load(path / "models.joblib")
    require(digest(saved["calibrators"]) == digest(metrics["calibrators"])
            and digest(saved["price_model"]) == digest(metrics["price_model"])
            and digest(saved["selection"]) == digest(metrics["selection"]), "r1_calibration_payload")
    original = existing_run(BASELINE)
    baseline, old_manifest = read_json(original / "metrics.json"), read_json(original / "manifest.json")
    require(digest(baseline) == old_manifest["metrics_sha256"]
            and hashlib.sha256((original / "models.joblib").read_bytes()).hexdigest() == metrics["base_model"]["model_sha256"], "r1_baseline_changed")
    for name in ("src/jra_srb/jra_research_r1_calibration.py", "src/jra_srb/jra_research_r1_live.py", "src/jra_srb/jra_research_tipster_twenty.py", "src/jra_srb/jra_research_tipster_residual.py", "scripts/run_jra_r1_calibration.py"):
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == manifest["code_sha256"][name], "r1_calibration_source_changed")
    for v in VARIANTS:
        require(metrics["calibrators"][v]["fit_through"] <= "2025-10-31", "r1_calibration_fit_date")
    require(.5 <= metrics["calibrators"]["C1"]["coefficient"] <= 2
            and 0 <= metrics["calibrators"]["C2"]["coefficient"] <= 1, "r1_calibration_fit_bounds")
    require(metrics["price_model"]["fit_through"] <= "2025-09-30"
            and all(.5 <= b["discount"] <= 1 for b in metrics["price_model"]["bands"]), "r1_price_fit_contract")
    rows, stream = [], hashlib.sha256(b"[")
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if rows:
                stream.update(b",")
            stream.update(canonical_json(row).encode("utf-8"))
            rows.append(row)
    stream.update(b"]")
    require(stream.hexdigest() == manifest["predictions_sha256"], "r1_calibration_prediction_hash")
    races = metrics["race_metrics"]
    race_map = {r["race_key"]: r for r in races}
    require(len(race_map) == len(races) and metrics["reference_races_reproduced"] == 1787, "r1_calibration_race_count")
    old_rows = {r["race_key"]: r for r in baseline["race_metrics"]}
    seen, mapped = set(), {}
    for r in rows:
        key = r["variant"], r["race_key"]
        require(key not in seen, "r1_calibration_duplicate_ticket")
        seen.add(key)
        mapped[key] = r
        v, policy = r["variant"].split("_")
        require(v in VARIANTS and policy in POLICIES, "r1_calibration_unknown_ticket")
        ticket = r["ticket"]
        require(ticket["kind"] == "quinella" and ticket["stake_yen"] == 600 and len(set(r["horses"])) == 2,
                "r1_calibration_ticket_contract")
        require(4 <= ticket["quoted_odds"] <= 80 and .015 <= r["probability"] <= 1
                and ticket["expected_multiplier"] >= 1.05, "r1_calibration_ticket_policy")
        factor = 1 if policy == "P0" else float(discounts(np.asarray([ticket["quoted_odds"]]), saved["price_model"])[0])
        near(ticket["price_factor"], factor, "r1_calibration_ticket_factor")
        near(r["probability"] * ticket["quoted_odds"] * factor, ticket["expected_multiplier"], "r1_calibration_ticket_ev")
        require(r["target"] in (0, 1) and bool(ticket["payout_yen"]) == bool(r["target"])
                and ticket["payout_yen"] % 6 == 0, "r1_calibration_ticket_settlement")
        require(r["split"] == race_map[r["race_key"]]["period"] and r["race_date"] == race_map[r["race_key"]]["race_date"], "r1_calibration_ticket_period")
    for r in races:
        if r["race_key"] in old_rows:
            near(r["loss"]["C0"], old_rows[r["race_key"]]["loss"]["R1"], "r1_calibration_reference_loss")
        for v in VARIANTS:
            for policy in POLICIES:
                key = v + "_" + policy
                ticket = mapped.get((key, r["race_key"]))
                require(r["stake"][key] == (ticket["ticket"]["stake_yen"] if ticket else 0)
                        and r["payout"][key] == (ticket["ticket"]["payout_yen"] if ticket else 0), "r1_calibration_missing_ticket")
    development = [r for r in races if r["period"] == "evaluation_2025"]
    dev = {v: float(np.mean([r["loss"][v] for r in development])) for v in VARIANTS}
    selected = next(v for v in VARIANTS if dev[v] <= min(dev.values()) + 1e-12)
    require(selected == metrics["selection"]["selected"], "r1_calibration_selection")
    groups = 0
    for v in VARIANTS:
        for period in PERIODS:
            subset = [r for r in races if in_period(r, period)]
            report = metrics["probability_results"][v][period]
            near(float(np.mean([r["loss"][v] for r in subset])) if subset else None, report["logloss"], "r1_calibration_mean_loss")
            require(digest(paired_interval(subset, v)) == digest({k: report[k] for k in paired_interval(subset, v)}), "r1_calibration_loss_interval")
            bins = metrics["reliability"][v][period]["all_pairs"]
            near(sum(b["predicted_hits"] for b in bins), len(subset), "r1_calibration_reliability_mass")
            require(sum(b["hits"] for b in bins) == len(subset), "r1_calibration_reliability_targets")
            for policy in POLICIES:
                key = v + "_" + policy
                chosen = [r for r in rows if r["variant"] == key and in_period(r, period)]
                expected = metrics["policy_results"][key][period]
                for field, value in accounting(chosen).items():
                    near(value, expected[field], "r1_calibration_accounting_" + field)
                groups += 1
    require(metrics["reload_score_checks"] == len(races) * 3, "r1_calibration_reload_count")
    comparison = {v: {p: price_comparison(races, v, p) for p in ("evaluation_2025", "reused_2026", "later_2026")} for v in VARIANTS}
    report = {"status": "passed", "run_id": run_id, "prediction_rows": len(rows), "accounting_groups": groups,
              "reference_races": 1787, "evaluation_races_including_calibration": len(races),
              "selected": selected, "hashes_verified": True, "baseline_model_unchanged": True,
              "source_hashes_verified": True, "probability_mass_verified": True, "development_selection_verified": True,
              "recorded_reload_score_checks": metrics["reload_score_checks"], "sql_queries": 0, "new_fits": 0,
              "verification_scope": "saved_artifact_integrity_not_independent_raw_data_replay",
              "verifier_sha256": hashlib.sha256((ROOT / "scripts/verify_jra_r1_calibration.py").read_bytes()).hexdigest()}
    write_once(path / "verification.json", report)
    write_once(path / "price-policy-comparison.json", comparison)
    return report


def main():
    """対象runを検証し、不整合は固定理由とともに停止する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.run_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
