"""概要: 完了済み非線形比較の保存成果物を再学習・SQL読取なしで独立照合する。
作成日: 2026-10-18
入力: --run-idで指定するspec160 runと、その基準spec150 runの保存成果物。
出力: 案件内residual-research-20261017に検証JSONと購入ペア診断JSON。
実行例: uv run --frozen --extra ml python scripts/verify_jra_tipster_boost.py --run-id <run-id>
注意事項: 原データ・旧成果物・運用を変更しない。新しい学習とSQL接続は行わない。
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

import joblib
import numpy as np

from jra_srb.jra_research_artifacts import ROOT, existing_run
from jra_srb.jra_research_contracts import canonical_json, digest
from jra_srb.jra_research_tipster_residual import bootstrap


DESTINATION = ROOT / ".workstate/jra-srb/sqlserver-model-data-audit/residual-research-20261017"
VARIANTS = ("M0", "R1", "R2", "B1", "B2")


def load_json(path):
    """保存JSONをUTF-8で読む。"""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, reason):
    """検証不一致を固定理由コードで停止する。"""
    if not condition:
        raise ValueError(reason)


def same(actual, expected, path="value"):
    """入れ子構造・数値・配列を比較し、不一致項目だけを示す。"""
    if isinstance(actual, dict):
        require(isinstance(expected, dict) and actual.keys() == expected.keys(), path + ":keys")
        for key in actual:
            same(actual[key], expected[key], path + "/" + str(key))
    elif isinstance(actual, (list, tuple)):
        require(len(actual) == len(expected), path + ":length")
        for i, value in enumerate(actual):
            same(value, expected[i], path + "/" + str(i))
    elif isinstance(actual, np.ndarray):
        require(np.array_equal(actual, expected), path + ":array")
    elif isinstance(actual, (float, np.floating)):
        require(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), path + ":number")
    else:
        require(actual == expected, path + ":value")


def predictions(path):
    """保存購入ペアをストリームで読み、canonical配列のhashを照合する。"""
    manifest = load_json(path / "manifest.json")
    rows, stream = [], hashlib.sha256(b"[")
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if rows:
                stream.update(b",")
            stream.update(canonical_json(row).encode("utf-8"))
            rows.append(row)
    stream.update(b"]")
    require(stream.hexdigest() == manifest["predictions_sha256"], "prediction_hash")
    return rows


def summary(rows):
    """保存買い目だけから時系列会計・払戻集中・最大資金減少を再計算する。"""
    stake = sum(row["ticket"]["stake_yen"] for row in rows)
    payout = sum(row["ticket"]["payout_yen"] for row in rows)
    largest = max((row["ticket"]["payout_yen"] for row in rows), default=0)
    balance = peak = drawdown = 0
    for row in sorted(rows, key=lambda value: (value["race_date"], value["race_key"])):
        balance += row["ticket"]["payout_yen"] - row["ticket"]["stake_yen"]
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    return {"races": len(rows), "days": len({r["race_date"] for r in rows}),
            "stake_yen": stake, "payout_yen": payout, "profit_yen": payout - stake,
            "return_rate": payout / stake if stake else None, "max_drawdown_yen": drawdown,
            "top_payout_share": largest / payout if payout else None,
            "return_rate_without_top_payout": (payout - largest) / stake if stake else None}


def included(row, period):
    """事前固定の暦分割に属するかを判定する。"""
    return row["period"] == period or period == "reused_2026" and row["period"] in ("evaluation_early", "evaluation_late")


def write_evidence(path, value):
    """同じ証跡の再確認は許可し、異なる既存証跡の上書きを拒否する。"""
    if path.exists():
        same(load_json(path), value, str(path.name))
    else:
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def verify(run_id):
    """spec160の保存値と基準runを照合し、成功時だけ検証証跡を保存する。

    Args:
        run_id: 完了した非線形比較runの識別子。
    Returns:
        dict: 検査件数・選択案・成功基準判定。
    Raises:
        ValueError: hash、購入条件、会計、モデル、期間等の不整合。
    Notes:
        元のrunは読み取るだけ。保存予測以外の価格や特徴を補完しない。
        run内の全ペア推論検査は既存証跡として区別して記録する。
    """
    path = existing_run(run_id)
    manifest, metrics, config = (load_json(path / name) for name in ("manifest.json", "metrics.json", "config.json"))
    require(manifest["status"] == "complete" and metrics["status"] == "passed", "run_status")
    require(config["protocol"] == "spec160-market-residual-boost-v1", "protocol")
    require(digest(metrics) == manifest["metrics_sha256"], "metrics_hash")
    require(hashlib.sha256((path / "models.joblib").read_bytes()).hexdigest() == metrics["model_sha256"], "model_hash")
    baseline_path = existing_run(metrics["baseline_run"])
    baseline = load_json(baseline_path / "metrics.json")
    baseline_manifest = load_json(baseline_path / "manifest.json")
    require(baseline_manifest["status"] == "complete", "baseline_status")
    require(digest(baseline) == baseline_manifest["metrics_sha256"], "baseline_metrics_hash")
    require(hashlib.sha256((baseline_path / "models.joblib").read_bytes()).hexdigest() == baseline["model_sha256"], "baseline_model_hash")
    for key in ("input_digest", "market_digest", "adopted_by_split", "years"):
        same(metrics["coverage"][key], baseline["coverage"][key], key)
    payload, old = joblib.load(path / "models.joblib"), joblib.load(baseline_path / "models.joblib")["models"]
    same(payload["config"], config, "model_config")
    same(payload["selection"], metrics["selection"], "model_selection")
    for name in ("M0", "R1", "R2"):
        same(payload["models"][name]["artifact"], old[name], "reused_model/" + name)
        require(old[name]["trained_through"] <= config["train"][1], "training_boundary")
    for name in ("B1", "B2"):
        artifact = payload["models"][name]["artifact"]
        require(len(artifact["trees"]) == config["rounds"] == 100 and artifact["learning_rate"] == .05, "boost_settings")
        for index, tree in enumerate(artifact["trees"]):
            params = tree.get_params()
            require(params["random_state"] == 102 + index and params["max_leaf_nodes"] == 6
                    and params["min_samples_leaf"] == 150, "tree_settings")
    code_checked = 0
    for name, expected in manifest["code_sha256"].items():
        source = ROOT / name
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            source = DESTINATION / "source-snapshots" / run_id / name
        require(source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() == expected, "code_hash/" + name)
        code_checked += 1
    for name in ("src/jra_srb/jra_research_tipster_boost.py", "scripts/run_jra_tipster_boost.py", "scripts/verify_jra_tipster_boost.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8-sig"))
        require(bool(ast.get_docstring(tree)), "file_header/" + name)
        require(all(ast.get_docstring(node) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))), "docstrings/" + name)
    race_rows = metrics["race_metrics"]
    race_map = {row["race_key"]: row for row in race_rows}
    require(len(race_map) == len(race_rows) == 1787, "race_count")
    baseline_races = {row["race_key"]: row for row in baseline["race_metrics"]}
    same(set(race_map), set(baseline_races), "reference_races")
    require(sum(row["period"].startswith("evaluation") for row in race_rows) == 1567, "common_reference_races")
    require(metrics["reload_score_checks"] == len(race_rows) * len(VARIANTS) == 8935, "recorded_reload_checks")
    rows = predictions(path)
    baseline_rows = predictions(baseline_path)
    old_predictions = {(row["variant"], row["race_key"]): row for row in baseline_rows if row["variant"] in ("M0", "R1", "R2")}
    reused = {(row["variant"], row["race_key"]): row for row in rows if row["variant"] in ("M0", "R1", "R2")}
    same(reused, old_predictions, "linear_predictions")
    selected = metrics["selection"]["selected"]
    development = [r for r in race_rows if r["period"] == "evaluation_2025"]
    development_losses = {name: float(np.mean([r["loss"][name] for r in development])) for name in VARIANTS}
    same(development_losses, metrics["selection"]["development_losses"], "development_losses")
    require(selected == min(VARIANTS, key=lambda name: (development_losses[name], name)), "development_selection")
    seen, totals = set(), defaultdict(Counter)
    for row in rows:
        key = row["variant"], row["race_key"]
        require(key not in seen and row["variant"] in VARIANTS, "duplicate_or_unknown_prediction")
        seen.add(key)
        race = race_map[row["race_key"]]
        require(row["split"] == race["period"] and row["race_date"] == race["race_date"], "prediction_period")
        ticket, q = row["ticket"], row["probability"]
        require(ticket["kind"] == "quinella" and ticket["stake_yen"] == 600, "ticket_budget")
        require(len(row["horses"]) == 2 and len(set(row["horses"])) == 2, "ticket_pair")
        require(.015 <= q <= 1 and math.isfinite(q) and 4 <= ticket["quoted_odds"] <= 80, "ticket_policy")
        require(q * ticket["quoted_odds"] >= 1.05, "ticket_expected_return")
        same(q * ticket["quoted_odds"], ticket["expected_multiplier"], "quoted_ev")
        require(row["target"] in (0, 1) and ticket["payout_yen"] >= 0 and ticket["payout_yen"] % 6 == 0, "settlement_units")
        require(bool(ticket["payout_yen"]) == bool(row["target"]), "hit_settlement")
        same(ticket["stake_yen"], race["stake"][row["variant"]], "race_stake")
        same(ticket["payout_yen"], race["payout"][row["variant"]], "race_payout")
        totals[key].update(stake=ticket["stake_yen"], payout=ticket["payout_yen"])
    groups = 0
    for name in VARIANTS:
        for race in race_rows:
            values = totals[(name, race["race_key"])]
            same(values["stake"], race["stake"][name], "missing_prediction_stake")
            same(values["payout"], race["payout"][name], "missing_prediction_payout")
            if name in ("M0", "R1", "R2"):
                same(race["loss"][name], baseline_races[race["race_key"]]["loss"][name], "linear_reference_loss")
        for period, expected in metrics["results"][name].items():
            group = [r for r in race_rows if included(r, period)]
            chosen = [r for r in rows if r["variant"] == name and included({"period": r["split"]}, period)]
            for key, value in summary(chosen).items():
                same(value, expected[key], "accounting/" + name + "/" + period + "/" + key)
            same(len(group), expected["evaluation_races"], "evaluation_count")
            same(float(np.mean([r["loss"][name] for r in group])), expected["logloss"], "logloss")
            same(bootstrap(group, name), expected["uncertainty"], "bootstrap/" + name + "/" + period)
            groups += 1
    result = metrics["results"][selected]["reused_2026"]
    criteria = {"roi_over_100": (result["return_rate"] or 0) > 1,
                "early_roi_over_100": (metrics["results"][selected]["evaluation_early"]["return_rate"] or 0) > 1,
                "late_roi_over_100": (metrics["results"][selected]["evaluation_late"]["return_rate"] or 0) > 1,
                "purchase_days_at_least_30": result["days"] >= 30,
                "roi_95_lower_over_100": result["uncertainty"]["roi_95"][0] > 1}
    require(all(criteria.values()) == metrics["purchase_success_criteria_met"], "purchase_criteria")
    diagnostics = {"run_id": run_id, "selected": selected, "success_conditions": criteria, "variants": {}}
    for name in VARIANTS:
        group = [r for r in rows if r["variant"] == name and r["split"] in ("evaluation_early", "evaluation_late")]
        hits = [r for r in group if r["target"]]
        diagnostics["variants"][name] = {"bets": len(group), "hits": len(hits),
            "expected_hits": sum(r["probability"] for r in group),
            "mean_predicted_probability": float(np.mean([r["probability"] for r in group])) if group else None,
            "observed_hit_rate": len(hits) / len(group) if group else None,
            "quoted_hit_return_yen": sum(r["ticket"]["quoted_odds"] * 600 for r in hits),
            "actual_return_yen": sum(r["ticket"]["payout_yen"] for r in hits),
            "actual_return_below_quote_hits": sum(r["ticket"]["payout_yen"] < r["ticket"]["quoted_odds"] * 600 for r in hits)}
    report = {"status": "passed", "run_id": run_id, "variants": list(VARIANTS), "prediction_rows": len(rows),
              "accounting_groups": groups, "common_reference_races": 1567, "all_diagnostic_races": len(race_rows),
              "linear_models_reused_verified": ["M0", "R1", "R2"], "linear_predictions_and_losses_reproduced": True,
              "boost_tree_counts": {"B1": 100, "B2": 100}, "prediction_hash_verified": True,
              "metrics_hash_verified": True, "model_hash_verified": True, "code_hashes_verified": code_checked,
              "bootstrap_reproduced_groups": groups, "recorded_run_reload_checks": metrics["reload_score_checks"],
              "selected": selected, "purchase_success_criteria_met": all(criteria.values()),
              "config_protocol": config["protocol"], "sql_queries": 0, "new_fits": 0, "pytest_executed": False,
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    DESTINATION.mkdir(parents=True, exist_ok=True)
    write_evidence(DESTINATION / (run_id + "-verification.json"), report)
    write_evidence(DESTINATION / (run_id + "-purchase-diagnostic.json"), diagnostics)
    return report


def main():
    """指定runを検証し、固定理由の失敗証跡または成功結果を出力する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.run_id), ensure_ascii=False))
    except Exception as error:
        failed = {"status": "failed", "error_type": type(error).__name__,
                  "reason": str(error) if isinstance(error, ValueError) else "artifact_verification_error"}
        DESTINATION.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        write_evidence(DESTINATION / ("boost-verification-failed-" + stamp + ".json"), failed)
        print(json.dumps(failed, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
