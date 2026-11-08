"""概要: 終了基準付きR1比較の合否と保存成果物を再学習せず照合する。
作成日: 2026-10-18
入力: --run-idで指定する完了run。
出力: 同runのverification.jsonと標準出力。
実行例: uv run --frozen --extra ml python scripts/verify_jra_r1_timing.py --run-id <run-id>
注意事項: SQL読取・再学習・既定変更なし。性能不合格も正常な研究結果として検証する。
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math

import numpy as np

from jra_srb.jra_research_artifacts import ROOT, existing_run
from jra_srb.jra_research_contracts import canonical_json, digest
from jra_srb.jra_research_r1_live import read_json, require
from jra_srb.jra_research_r1_timing import CONFIG, VARIANTS, accuracy_gate, purchase_gate, summaries


def near(actual, expected):
    """欠測を区別して数値の保存後丸め誤差だけを許容する。"""
    require(actual is expected if actual is None or expected is None else math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), "timing_verification_numeric_mismatch")


def verify(run_id):
    """hash・会計・基準・終了判断を保存値と再集計で確認する。"""
    path = existing_run(run_id)
    manifest, metrics, config, coverage = (read_json(path / name) for name in ("manifest.json", "metrics.json", "config.json", "coverage.json"))
    require(manifest["status"] == "complete" and metrics["status"] == "passed", "timing_verify_incomplete")
    require(digest(metrics) == manifest["metrics_sha256"], "timing_verify_metrics_hash")
    require(all(config[k] == v for k, v in CONFIG.items()), "timing_verify_config_changed")
    for name in ("src/jra_srb/jra_research_r1_timing.py", "scripts/run_jra_r1_timing.py"):
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == manifest["code_sha256"][name], "timing_verify_source_changed")
    original = existing_run(metrics["base_model"]["baseline_run"]) / "models.joblib"
    require(hashlib.sha256(original.read_bytes()).hexdigest() == metrics["base_model"]["model_sha256"], "timing_verify_original_model_changed")
    tickets, stream = [], hashlib.sha256(b"[")
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if tickets:
                stream.update(b",")
            stream.update(canonical_json(row).encode("utf-8"))
            tickets.append(row)
    stream.update(b"]")
    require(stream.hexdigest() == manifest["predictions_sha256"], "timing_verify_prediction_hash")
    race_map = {r["race_key"]: r for r in metrics["race_metrics"]}
    require(len(race_map) == len(metrics["race_metrics"]), "timing_verify_duplicate_race")
    seen, values = set(), defaultdict(lambda: [0, 0])
    for t in tickets:
        key = t["race_key"], t["variant"]
        require(key not in seen and t["variant"] in VARIANTS, "timing_verify_duplicate_ticket")
        seen.add(key)
        ticket = t["ticket"]
        require(ticket["stake_yen"] == 600 and ticket["kind"] == "quinella" and len(set(t["horses"])) == 2,
                "timing_verify_ticket_contract")
        require(4 <= ticket["quoted_odds"] <= 80 and .015 <= t["probability"] <= 1
                and ticket["expected_multiplier"] >= 1.05, "timing_verify_ticket_policy")
        near(t["probability"] * ticket["quoted_odds"], ticket["expected_multiplier"])
        require(t["target"] in (0, 1) and bool(ticket["payout_yen"]) == bool(t["target"])
                and ticket["payout_yen"] % 6 == 0, "timing_verify_settlement")
        require(t["split"] == race_map[t["race_key"]]["period"] and t["race_date"] == race_map[t["race_key"]]["race_date"], "timing_verify_ticket_scope")
        values[key] = [ticket["stake_yen"], ticket["payout_yen"]]
    for key, r in race_map.items():
        for v in VARIANTS:
            require(values[(key, v)] == [r["stake"][v], r["payout"][v]], "timing_verify_accounting")
    development = [r for r in race_map.values() if r["period"] == "evaluation_2025"]
    gate = accuracy_gate(development, coverage["development_expected"], "development")
    require(digest(gate) == digest(metrics["development_gate"]), "timing_verify_gate_reproduction")
    summary = summaries(development, [t for t in tickets if t["split"] == "evaluation_2025"])
    require(digest(summary) == digest(metrics["development_results"]), "timing_verify_summary")
    # 最小改善幅を報告上の合否だけに依存せず、競走別の平均から再確認する。
    means = {v: float(np.mean([r["loss"][v] for r in development])) for v in VARIANTS}
    near((means["R30"] - means["R10"]) / means["R30"], gate["vs_r30"]["relative_gain"])
    near((means["M10"] - means["R10"]) / means["M10"], gate["vs_m10"]["relative_gain"])
    if not gate["passed"]:
        require(metrics["evaluation_gate"] is None and metrics["evaluation_results"] is None
                and not metrics["evaluation_executed"] and coverage["evaluation_adopted"] == 0
                and coverage["evaluation_market_not_read_when_screen_failed"]
                and len(race_map) == len(development), "timing_verify_failed_gate_did_not_stop")
        require(metrics["decision"]["research_status"] == "closed_failed_performance_gate", "timing_verify_missing_closure")
    else:
        evaluation = [r for r in race_map.values() if r["period"] != "evaluation_2025"]
        final = accuracy_gate(evaluation, coverage["evaluation_expected"], "evaluation")
        for period in ("evaluation_early", "evaluation_late", "later_2026"):
            subset = [r for r in evaluation if r["period"] == period]
            final["checks"]["non_worse_" + period] = bool(subset) and bool(
                np.mean([r["loss"]["R10"] for r in subset]) <= np.mean([r["loss"]["R30"] for r in subset]))
        final["passed"] = all(final["checks"].values())
        require(digest(final) == digest(metrics["evaluation_gate"]), "timing_verify_final_gate")
        purchase = purchase_gate(evaluation, [t for t in tickets if t["split"] != "evaluation_2025"])
        require(digest(purchase) == digest(metrics["evaluation_results"]), "timing_verify_purchase_gate")
        require(metrics["evaluation_executed"] and coverage["evaluation_adopted"] == len(evaluation)
                and metrics["decision"]["accuracy_candidate_supported"] == final["passed"], "timing_verify_evaluation_scope")
        expected_status = "prospective_validation_only" if final["passed"] else "closed_failed_performance_gate"
        require(metrics["decision"]["research_status"] == expected_status, "timing_verify_final_decision")
    require(metrics["decision"]["stop_further_tuning"] and metrics["decision"]["next_variants_allowed"] == 0
            and metrics["new_fits"] == 0 and not metrics["default_changed"], "timing_verify_research_limit")
    report = {"status": "passed", "run_id": run_id, "prediction_rows": len(tickets), "races": len(race_map),
              "development_gate_reproduced": True, "minimum_improvement_recomputed": True, "hashes_verified": True,
              "original_model_unchanged": True, "research_status": metrics["decision"]["research_status"],
              "further_variants_allowed": 0, "sql_queries": 0, "new_fits": 0,
              "scope": "saved_artifact_integrity_and_stop_decision",
              "verifier_sha256": hashlib.sha256((ROOT / "scripts/verify_jra_r1_timing.py").read_bytes()).hexdigest()}
    target = path / "verification.json"
    if target.exists():
        require(digest(read_json(target)) == digest(report), "timing_verify_existing_report_differs")
    else:
        with target.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    """指定runの検証結果を表示する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    print(json.dumps(verify(parser.parse_args().run_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
