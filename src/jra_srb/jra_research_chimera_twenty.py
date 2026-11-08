"""概要: 新キメラ20仮説の固定期間入力を判定し、条件未達なら学習前に停止する。
作成日: 2026-10-18
入力: spec230/231、監査済み2025年SQL原文、snapshot31のT30馬連/HR。
出力: 一意な研究run、競走別採否、月別充足、学習前停止判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_twenty.py --preflight-only
注意事項: SQLは読取のみ。95%未達時は20案とも未学習。既定変更・実購入なし。
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest, timestamp
from .jra_research_features import numeric_market
from .jra_research_history import HistoryConfig
from .jra_research_r1_live import LiveAnnualReader, read_json, require
from .jra_research_r1_timing import indexed_rows
from . import jra_research_chimera as chimera
from . import jra_research_tipster_twenty as native
from . import jra_research_tipster_experiment as prior
from . import jra_research_tipster_smoke as base


CASES = tuple(f"H{i:02d}" for i in range(1, 21))
CONFIG = {"protocol": "spec230-231-chimera-twenty-v1", "cases": list(CASES),
          "primary": ["2025-01-01", "2025-06-30"], "secondary": ["2025-07-01", "2025-09-30"],
          "min_coverage": .95, "history_before": "2026-10-18", "market_snapshot": 31,
          "horizon": "T30", "max_primary_candidates": 20, "max_secondary_candidates": 3,
          "max_final_candidates": 1, "default_changed": False, "unseen_test": False}


def split_for(day):
    """対象日を固定した一次・二次へ分け、対象外ならNoneを返す。"""
    for name in ("primary", "secondary"):
        if CONFIG[name][0] <= day <= CONFIG[name][1]:
            return name
    return None


def validate_inputs(race, markets, payouts):
    """競走の全ペアT30とHRを検査し、数値価格を返す。

    Args:
        race: 監査済み原文から解析した正常競走。
        markets: 同一競走・同一T30の馬連市場行。
        payouts: 公表済み馬連払戻行。
    Returns:
        dict: 全馬連組の数値オッズ。
    Raises:
        ResearchError: 欠測、重複、時点・馬集合・確定結果との不整合。
    """
    require(len(markets) == 1, "missing_T30" if not markets else "duplicate_T30")
    row = markets[0]
    require(row["horizon"] == "T30" and row["market"] == "quinella"
            and row["selection_status"] == "selected" and row["parser_version"] == "jv-o1o2-v2"
            and bool(row["content_sha256"]), "invalid_T30_identity")
    require(timestamp(row["announced_at"]) <= timestamp(row["cutoff_at"]), "T30_announced_after_cutoff")
    prices = numeric_market(row, "quinella")
    expected = set(combinations([r["horse_no"] for r in race["runners"]], 2))
    require(set(prices) == expected, "T30_pair_roster_mismatch")
    require(len(payouts) == 1, "missing_HR" if not payouts else "duplicate_HR")
    payout = payouts[0]
    winner = "".join(r["horse_no"] for r in race["runners"] if r["rank"] <= 2)
    require(payout["market"] == "quinella" and payout["slot_status"] == "published"
            and bool(payout["hr_sha256"]) and payout["selection_raw"] == winner
            and payout["payout_yen"] > 0 and str(payout["payout_raw"]).strip().isdigit()
            and int(payout["payout_raw"]) == payout["payout_yen"], "invalid_HR")
    return prices


def coverage_summary(rows):
    """競走別の採否を独立に集計し、両期間の95%条件を判定する。"""
    splits, months = {}, {}
    for key in ("primary", "secondary"):
        selected = [r for r in rows if r["split"] == key]
        good = sum(r["valid"] for r in selected)
        splits[key] = {"expected": len(selected), "valid": good,
                       "coverage": good / len(selected) if selected else 0,
                       "days": len({r["race_date"] for r in selected}),
                       "valid_days": len({r["race_date"] for r in selected if r["valid"]}),
                       "reasons": dict(Counter(r["reason"] for r in selected if not r["valid"]))}
    for month in sorted({r["race_date"][:7] for r in rows}):
        selected = [r for r in rows if r["race_date"].startswith(month)]
        months[month] = {"expected": len(selected), "valid": sum(r["valid"] for r in selected),
                         "reasons": dict(Counter(r["reason"] for r in selected if not r["valid"]))}
    return {"splits": splits, "months": months,
            "passed": all(s["expected"] > 0 and s["coverage"] >= CONFIG["min_coverage"] for s in splits.values())}


def input_preflight(artifacts):
    """2025年だけを読み、対象全競走のT30/HR採否を保存する。

    Args:
        artifacts: 一意runの保存先。
    Returns:
        dict: 競走別採否、年別照合、期間/月別集計、固定入力digest。
    Notes:
        全期間データ監査やモデル再学習は行わない。市場照会は100競走ずつ。
    """
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    audit = read_json(chimera.AUDIT / "audit.json")
    verified = read_json(chimera.AUDIT / "verification.json")
    require(audit["status"] == "complete" and verified["status"] == "passed", "twenty_missing_audit")
    with LiveAnnualReader(config) as reader:
        annual_preflight = reader.preflight()
        raw, annual = reader.year_before(2025, CONFIG["history_before"])
    require(annual["input_digest"] == audit["annual"]["2025"]["source_audit"]["input_digest"],
            "twenty_2025_input_changed")
    races, normal = {}, 0
    for key, source in sorted(raw.items()):
        race, reason = native.parse_race(key, source)
        if reason is None:
            normal += 1
            if split_for(race["day"]):
                races[key] = race
    require(normal == audit["annual"]["2025"]["counts"]["races"], "twenty_2025_cohort_changed")
    del raw
    rows, input_hash = [], hashlib.sha256()
    keys = sorted(races)
    print(json.dumps({"stage": "input_preflight", "expected": len(keys), "normal_2025": normal}), flush=True)
    with prior.ExperimentMarketReader(config) as reader:
        reader.selected(["2025-11-01"])
        for begin in range(0, len(keys), 100):
            batch = keys[begin:begin + 100]
            markets = indexed_rows(reader, batch, "market.odds_asof_index", base.FIELDS["market.odds_asof_index"],
                                   "AND t.market=N'quinella' AND t.horizon=N'T30'")
            payouts = indexed_rows(reader, batch, "history.payouts", base.FIELDS["history.payouts"],
                                   "AND t.market=N'quinella' AND t.slot_status=N'published'")
            by_market, by_payout = defaultdict(list), defaultdict(list)
            for row in markets:
                by_market[row["race_key"]].append(row)
            for row in payouts:
                by_payout[row["race_key"]].append(row)
            input_hash.update(digest({"keys": batch, "markets": markets, "payouts": payouts}).encode())
            for key in batch:
                race, reason = races[key], None
                try:
                    validate_inputs(race, by_market[key], by_payout[key])
                except ResearchError as error:
                    reason = error.reason
                rows.append({"race_key": key, "race_date": race["day"], "split": split_for(race["day"]),
                             "valid": reason is None, "reason": reason})
            artifacts.write_json("coverage.json", {"stage": "preflight", "checked": len(rows), "expected": len(keys),
                                                    **coverage_summary(rows), "race_inputs": rows})
            print(json.dumps({"stage": "input_checked", "checked": len(rows), "valid": sum(r["valid"] for r in rows)}), flush=True)
        query_metrics = reader.query_metrics
    return {"annual": {"input_digest": annual["input_digest"], "normal_races": normal},
            "annual_preflight": annual_preflight, "market_input_digest": input_hash.hexdigest(),
            "query_metrics": query_metrics, "race_inputs": rows, **coverage_summary(rows)}


def execute_preflight():
    """事前条件を実測し、不足なら学習を開始せず正式な入力停止結果を残す。"""
    base.install_input_guard()
    artifacts = RunArtifacts(CONFIG, "chimera-twenty-input-preflight")
    for name in ("scripts/run_jra_chimera_twenty.py", "scripts/verify_jra_chimera_twenty.py"):
        artifacts.manifest["code_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    artifacts.manifest["spec_sha256"] = {str(i): hashlib.sha256(next((ROOT / ".workstate/jra-srb/sqlserver-model-data-audit/spec").glob(str(i) + "-*.md")).read_bytes()).hexdigest() for i in (230, 231)}
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        report = input_preflight(artifacts)
        artifacts.write_json("preflight.json", report)
        metrics = {"stage": "input_preflight", "input_ready": report["passed"],
                   "research_status": "ready_for_fixed_implementation" if report["passed"] else "stopped_input_coverage",
                   "case_status": {name: "not_trained_not_evaluated" for name in CASES},
                   "model_fits": 0, "performance_evaluated": False, "default_changed": False,
                   "splits": report["splits"], "months": report["months"]}
        artifacts.write_json("coverage.json", report)
        artifacts.write_json("metrics.json", metrics)
        prediction_hash = artifacts.write_predictions([])
        artifacts.finish(overall_complete=False, metrics_sha256=digest(metrics), predictions_sha256=prediction_hash,
                         preflight_sha256=digest(report), research_status=metrics["research_status"],
                         performance_gate_passed=False)
        return {"run_id": artifacts.run_id, **metrics}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("twenty_preflight_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None


def verify_preflight(run_id):
    """SQL再読取・学習なしで、保存した全競走の採否と停止を再集計する。"""
    path = existing_run(run_id)
    manifest, metrics = read_json(path / "manifest.json"), read_json(path / "metrics.json")
    report, config = read_json(path / "preflight.json"), read_json(path / "config.json")
    require(manifest["status"] == "complete" and digest(metrics) == manifest["metrics_sha256"]
            and digest(report) == manifest["preflight_sha256"], "twenty_artifact_hash")
    require(config == CONFIG, "twenty_config_changed")
    rows = report["race_inputs"]
    require(len({r["race_key"] for r in rows}) == len(rows), "twenty_duplicate_cohort")
    for row in rows:
        require(row["split"] == split_for(row["race_date"]) and bool(row["valid"]) == (row["reason"] is None),
                "twenty_invalid_saved_row")
    # 実行時の集計関数を呼ばず、独立したカウンタで同じ値を検証する。
    for name in ("primary", "secondary"):
        selected = [r for r in rows if r["split"] == name]
        valid = [r for r in selected if r["valid"]]
        expected = {"expected": len(selected), "valid": len(valid),
                    "coverage": len(valid) / len(selected) if selected else 0,
                    "days": len(set(r["race_date"] for r in selected)),
                    "valid_days": len(set(r["race_date"] for r in valid)),
                    "reasons": dict(Counter(r["reason"] for r in selected if not r["valid"]))}
        require(expected == report["splits"][name] == metrics["splits"][name], "twenty_saved_counts")
    for month in sorted(set(r["race_date"][:7] for r in rows)):
        selected = [r for r in rows if r["race_date"][:7] == month]
        require(report["months"][month] == metrics["months"][month] == {
            "expected": len(selected), "valid": sum(r["valid"] for r in selected),
            "reasons": dict(Counter(r["reason"] for r in selected if not r["valid"]))}, "twenty_saved_months")
    ready = all(s["expected"] and s["valid"] / s["expected"] >= .95 for s in report["splits"].values())
    require(bool(ready) == report["passed"] == metrics["input_ready"], "twenty_saved_decision")
    require(metrics["model_fits"] == 0 and not metrics["performance_evaluated"] and not metrics["default_changed"]
            and metrics["case_status"] == {name: "not_trained_not_evaluated" for name in CASES}, "twenty_unexpected_training")
    require(metrics["research_status"] == ("ready_for_fixed_implementation" if ready else "stopped_input_coverage"),
            "twenty_saved_stop")
    for filename, sha in manifest["code_sha256"].items():
        require(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == sha, "twenty_source_changed")
    for i, sha in manifest["spec_sha256"].items():
        require(hashlib.sha256(next((ROOT / ".workstate/jra-srb/sqlserver-model-data-audit/spec").glob(i + "-*.md")).read_bytes()).hexdigest() == sha,
                "twenty_spec_changed")
    output = {"status": "passed", "run_id": run_id, "races": len(rows), "model_fits": 0,
              "sql_reads": 0, "input_ready": bool(ready), "research_status": metrics["research_status"]}
    (path / "verification.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
