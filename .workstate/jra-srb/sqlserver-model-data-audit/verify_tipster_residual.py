"""概要: 市場残差研究の保存予測・会計・入力集合を独立照合する。
作成日: 2026-10-17
入力: --run-idで指定した新研究runと固定した既存研究のJSON成果物。
出力: residual-research-20261017/<run-id>-verification.json。
実行例: uv run --frozen --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/verify_tipster_residual.py --run-id <run-id>
注意事項: SQL接続・学習・原データ読取・既存run上書きなし。
"""

import argparse
import ast
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from jra_srb.jra_research_artifacts import existing_run
from jra_srb.jra_research_contracts import canonical_json, digest


def load(path):
    """UTF-8の成果物JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def verify(run_id):
    """学習境界・集合・会計・hash・成功判定を照合して結果を記録する。"""
    path = existing_run(run_id)
    m, manifest = load(path / "metrics.json"), load(path / "manifest.json")
    config = load(path / "config.json")
    assert manifest["status"] == "complete" and m["status"] == "passed"
    assert digest(m) == manifest["metrics_sha256"]
    assert hashlib.sha256((path / "models.joblib").read_bytes()).hexdigest() == m["model_sha256"]
    bundle = joblib.load(path / "models.joblib")
    for model in bundle["models"].values():
        linear = model["artifact"] if model.get("kind") == "linear" else model
        if "trained_through" in linear:
            assert linear["trained_through"] <= "2025-09-30"
    if "baseline_run" in m:
        baseline = existing_run(m["baseline_run"])
        old_metrics = load(baseline / "metrics.json")
        assert hashlib.sha256((baseline / "models.joblib").read_bytes()).hexdigest() == old_metrics["model_sha256"]
        original = joblib.load(baseline / "models.joblib")["models"]
        for name in m["linear_models_reused"]:
            reused = bundle["models"][name]["artifact"]
            for field in ("coef", "scale"):
                np.testing.assert_array_equal(reused[field], original[name][field])
        for field in ("input_digest", "market_digest", "adopted_by_split"):
            assert m["coverage"][field] == old_metrics["coverage"][field]
        assert m["new_fits"] == 2
    assert m["selection"]["selected"] == min(m["selection"]["development_losses"], key=lambda k: (m["selection"]["development_losses"][k], k))
    assert not m["sqlite_used"] and not m["live_adopted"] and not m["unseen_test"]
    reference = load(existing_run("20261017T101337Z_24a898f583fd464093472afb87a88f28") / "metrics.json")
    expected = {r["race_key"]: r for r in reference["race_metrics"]}
    actual = {r["race_key"]: r for r in m["race_metrics"] if r["period"] != "calibration"}
    assert set(actual) == set(expected)
    assert m["coverage"]["input_digest"] == reference["coverage"]["input_digest"]
    for key, row in actual.items():
        assert np.isclose(row["loss"]["M0"], expected[key]["loss"]["market"], atol=1e-12, rtol=0)
    stream, rows, unique, account = hashlib.sha256(b"["), 0, set(), defaultdict(Counter)
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as handle:
        for row in map(json.loads, handle):
            if rows:
                stream.update(b",")
            stream.update(canonical_json(row).encode())
            rows += 1
            key = (row["race_key"], row["variant"])
            assert key not in unique
            unique.add(key)
            ticket = row["ticket"]
            assert ticket["stake_yen"] == 600 and ticket["kind"] == "quinella"
            assert 4 <= ticket["quoted_odds"] <= 80 and row["probability"] >= .015
            assert ticket["expected_multiplier"] >= 1.05
            assert np.isclose(ticket["expected_multiplier"], row["probability"] * ticket["quoted_odds"])
            assert (ticket["payout_yen"] > 0) == bool(row["target"])
            for period in (row["split"], *(["reused_2026"] if row["race_date"].startswith("2026") else [])):
                account[row["variant"], period].update(races=1, stake_yen=600, payout_yen=ticket["payout_yen"])
    stream.update(b"]")
    assert stream.hexdigest() == manifest["predictions_sha256"]
    checked = 0
    for name, result in m["results"].items():
        for period, metrics in result.items():
            counts = account[name, period]
            for key in ("races", "stake_yen", "payout_yen"):
                assert metrics[key] == counts[key]
            assert metrics["profit_yen"] == counts["payout_yen"] - counts["stake_yen"]
            subset = [r for r in m["race_metrics"] if r["period"] == period or period == "reused_2026" and r["period"] in ("evaluation_early", "evaluation_late")]
            assert len(subset) == metrics["evaluation_races"]
            assert np.isclose(np.mean([r["loss"][name] for r in subset]), metrics["logloss"])
            assert sum(r["stake"][name] for r in subset) == counts["stake_yen"]
            assert sum(r["payout"][name] for r in subset) == counts["payout_yen"]
            if counts["stake_yen"]:
                assert np.isclose(metrics["return_rate"], counts["payout_yen"] / counts["stake_yen"])
            else:
                assert metrics["return_rate"] is None
            checked += 1
    assert all(value["success"] for value in m["optimizers"].values())
    root = Path(__file__).resolve().parents[3]
    for name, sha in manifest["code_sha256"].items():
        if name == "scripts/jra_second_ten_model.py":
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == sha
        if name in ("src/jra_srb/jra_research_tipster_residual.py", "scripts/run_jra_tipster_residual.py", "src/jra_srb/jra_research_tipster_boost.py", "scripts/run_jra_tipster_boost.py"):
            source = root / name
            assert hashlib.sha256(source.read_bytes()).hexdigest() == sha
            tree = ast.parse(source.read_text(encoding="utf-8"))
            assert ast.get_docstring(tree)
            assert all(ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)))
    output = Path(__file__).resolve().parent / "residual-research-20261017"
    output.mkdir(exist_ok=True)
    report = {"status": "passed", "run_id": run_id, "variants": list(m["results"]), "prediction_rows": rows,
              "accounting_groups": checked, "common_reference_races": len(actual), "market_losses_reproduced": True,
              "prediction_hash_verified": True, "metrics_hash_verified": True, "model_hash_verified": True,
              "selected": m["selection"]["selected"], "purchase_success_criteria_met": m["purchase_success_criteria_met"],
              "pytest_executed": False, "config_protocol": config["protocol"]}
    (output / f"{run_id}-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    verify(parser.parse_args().run_id)
