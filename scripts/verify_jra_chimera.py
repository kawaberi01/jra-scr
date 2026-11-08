"""概要: キメラ固定比較の保存モデル・予測・会計・性能合否と停止を照合する。
作成日: 2026-10-18
入力: --run-idで指定する完了研究run。
出力: 同runのverification.jsonと標準出力。
実行例: uv run --frozen --extra ml python scripts/verify_jra_chimera.py --run-id <run-id>
注意事項: SQL読取・再学習なし。性能不合格も正常な完了として検証する。
"""

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
from jra_srb.jra_research_r1_live import read_json, require
from jra_srb.jra_research_chimera import CONFIG, ALL_VARIANTS, VARIANTS, accuracy_gate, purchase_gate, summaries


def near(actual, expected):
    """欠測と数値を区別し、保存後の丸め誤差だけを許容する。"""
    require(actual is expected if actual is None or expected is None else math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-12),
            "chimera_verify_numeric_difference")


def verify(run_id):
    """学習・SQL再読取をせず、保存証跡の整合と機械的な合否を再確認する。"""
    path = existing_run(run_id)
    manifest, config, metrics, coverage = (read_json(path / n) for n in ("manifest.json", "config.json", "metrics.json", "coverage.json"))
    require(manifest["status"] == "complete" and metrics["status"] == "passed", "chimera_verify_not_complete")
    require(digest(metrics) == manifest["metrics_sha256"] and all(config[k] == v for k, v in CONFIG.items()), "chimera_verify_contract")
    sources = ("src/jra_srb/jra_research_chimera.py", "src/jra_srb/jra_research_r1_timing.py",
               "src/jra_srb/jra_research_r1_calibration.py", "src/jra_srb/jra_research_tipster_twenty.py",
               "scripts/run_jra_chimera.py", "scripts/verify_jra_chimera.py")
    for name in sources:
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == manifest["code_sha256"][name], "chimera_verify_source_changed")
    require(hashlib.sha256((path / "models.joblib").read_bytes()).hexdigest() == manifest["model_sha256"], "chimera_verify_model_hash")
    payload = joblib.load(path / "models.joblib")
    require(digest(payload["config"]) == digest(CONFIG) and set(payload["models"]) == set(VARIANTS), "chimera_verify_model_contract")
    dimensions = {"A": 10, "AB": 18, "ABC": 22}
    for name, model in payload["models"].items():
        require(model["variant"] == name and model["coef"].shape == model["scale"].shape == (dimensions[name],)
                and np.isfinite(model["coef"]).all() and np.isfinite(model["scale"]).all() and np.all(model["scale"] > 0)
                and model["train_races"] == CONFIG["train_expected"] and model["optimizer"]["success"], "chimera_verify_model_shape")
    original = existing_run(metrics["base_model"]["baseline_run"]) / "models.joblib"
    require(hashlib.sha256(original.read_bytes()).hexdigest() == metrics["base_model"]["model_sha256"], "chimera_verify_original_model_changed")
    predictions, stream = [], hashlib.sha256(b"[")
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as source:
        for line in source:
            t = json.loads(line)
            if predictions:
                stream.update(b",")
            stream.update(canonical_json(t).encode("utf-8"))
            predictions.append(t)
    stream.update(b"]")
    require(stream.hexdigest() == manifest["predictions_sha256"], "chimera_verify_prediction_hash")
    rows = metrics["race_metrics"]
    race_map = {r["race_key"]: r for r in rows}
    require(len(race_map) == len(rows), "chimera_verify_duplicate_race")
    seen, accounting = set(), defaultdict(lambda: [0, 0])
    for t in predictions:
        key = t["race_key"], t["variant"]
        require(key not in seen and t["variant"] in ALL_VARIANTS and t["race_key"] in race_map, "chimera_verify_ticket_scope")
        seen.add(key)
        ticket = t["ticket"]
        require(ticket["kind"] == "quinella" and ticket["stake_yen"] == 600 and len(set(t["horses"])) == 2
                and 4 <= ticket["quoted_odds"] <= 80 and .015 <= t["probability"] <= 1
                and ticket["expected_multiplier"] >= 1.05, "chimera_verify_purchase_policy")
        near(ticket["expected_multiplier"], t["probability"] * ticket["quoted_odds"])
        require(t["target"] in (0, 1) and bool(ticket["payout_yen"]) == bool(t["target"])
                and ticket["payout_yen"] % 6 == 0 and t["split"] == race_map[t["race_key"]]["period"], "chimera_verify_settlement")
        accounting[key] = [ticket["stake_yen"], ticket["payout_yen"]]
    for r in rows:
        require(r["pair_count"] >= 28, "chimera_verify_pair_count")
        for name in ALL_VARIANTS:
            require(accounting[(r["race_key"], name)] == [r["stake"][name], r["payout"][name]], "chimera_verify_accounting")
            moment = r["moments"][name]
            require(0 < moment["winning_probability"] <= 1 and moment["minimum"] > 0
                    and 1 / r["pair_count"] - 1e-10 <= moment["squared_sum"] <= 1 + 1e-10, "chimera_verify_probability_moments")
            near(moment["sum"], 1)
            near(r["loss"][name], -math.log(moment["winning_probability"]))
            near(r["brier"][name], (moment["squared_sum"] - 2 * moment["winning_probability"] + 1) / r["pair_count"])
    dev = [r for r in rows if r["period"] == "evaluation_2025"]
    dev_tickets = [t for t in predictions if t["split"] == "evaluation_2025"]
    gate = accuracy_gate(dev, coverage["development_expected"], "development")
    require(digest(gate) == digest(metrics["development_gate"]), "chimera_verify_development_gate")
    require(digest(summaries(dev, dev_tickets)) == digest(metrics["development_results"]), "chimera_verify_summaries")
    if not gate["passed"]:
        require(not metrics["evaluation_executed"] and metrics["evaluation_gate"] is None and metrics["evaluation_results"] is None
                and coverage["evaluation_adopted"] == 0 and len(dev) == len(rows)
                and coverage["evaluation_market_not_read_when_screen_failed"], "chimera_verify_failed_gate_stop")
        supported = False
    else:
        evaluation = [r for r in rows if r["period"] != "evaluation_2025"]
        final = accuracy_gate(evaluation, coverage["evaluation_expected"], "evaluation")
        for period in ("evaluation_early", "evaluation_late", "later_2026"):
            subset = [r for r in evaluation if r["period"] == period]
            final["checks"]["non_worse_" + period] = bool(subset) and bool(np.mean([r["loss"]["ABC"] for r in subset]) <= np.mean([r["loss"]["R1"] for r in subset]))
        final["passed"] = all(final["checks"].values())
        require(digest(final) == digest(metrics["evaluation_gate"]) and metrics["evaluation_executed"], "chimera_verify_final_gate")
        purchases = purchase_gate(evaluation, [t for t in predictions if t["split"] != "evaluation_2025"])
        require(digest(purchases) == digest(metrics["evaluation_results"]), "chimera_verify_purchase_gate")
        supported = final["passed"]
    expected_status = "prospective_validation_only" if supported else "closed_failed_performance_gate"
    require(metrics["decision"]["research_status"] == expected_status and metrics["decision"]["accuracy_candidate_supported"] == supported
            and metrics["decision"]["stop_further_tuning"] and metrics["decision"]["next_variants_allowed"] == 0
            and metrics["model_fits"] == 3 and not metrics["default_changed"], "chimera_verify_decision")
    require(metrics["reload_score_checks"] == len(rows) * 3, "chimera_verify_reload_checks")
    report = {"status": "passed", "run_id": run_id, "races": len(rows), "prediction_rows": len(predictions),
              "model_variants": list(VARIANTS), "model_hashes_verified": True, "original_model_unchanged": True,
              "loss_brier_accounting_recomputed": True, "performance_gate_reproduced": True,
              "research_status": expected_status, "sql_reads": 0, "new_model_fits": 0,
              "scope": "saved_integrity_moments_accounting_gate_and_stop",
              "verifier_sha256": hashlib.sha256((ROOT / "scripts/verify_jra_chimera.py").read_bytes()).hexdigest()}
    target = path / "verification.json"
    if target.exists():
        require(digest(read_json(target)) == digest(report), "chimera_verify_existing_report_changed")
    else:
        with target.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    """指定runを照合し、検証結果を標準出力へ返す。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    print(json.dumps(verify(parser.parse_args().run_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
