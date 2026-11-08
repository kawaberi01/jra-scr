"""概要: R1を明示して発走前の参考馬連確率を作り、任意で共通SQLへ保存する。
作成日: 2026-10-18
入力: --date、--course、--race-no、--meeting-no、--meeting-day、--save。
出力: 研究runと標準出力。--save時は参考予想をSQL保存し読み戻す。
実行例: uv run --frozen --extra ml python scripts/score_jra_r1_live.py --date 2026-10-18 --course kyoto --race-no 11 --meeting-no 4 --meeting-day 7 --save
注意事項: 先にlocal-race-api-readyでAPIを確認する。再学習・自動購入・既定変更なし。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os

from jra_srb.jra_research_artifacts import ROOT, existing_run
from jra_srb.jra_research_contracts import ResearchError, digest
from jra_srb.jra_research_r1_live import COURSES, execute, require


def save_reference(result):
    """参考予想をSQL保存し、同じ時点束・全ペア・空の実購入券を読み戻す。

    Notes:
        通常予想の正式順位を変更せず、馬連参考として独立IDに保存する。
        トップ2周辺確率を勝率やトップ3順位として登録しない。
    """
    from jra_srb.storage import build_analysis_store
    from jra_srb.storage_config import storage_backend

    now = datetime.now(timezone.utc)
    require(now < datetime.fromisoformat(result["post_time"]), "r1_save_after_post")
    os.environ.setdefault("JRA_SRB_STORAGE_ENV_FILE", str(ROOT / "data/storage/runtime.env"))
    require(storage_backend() == "sqlserver", "r1_sql_backend_required")
    prediction_id = "jra-" + result["race_id"] + "-r1-reference-" + result["run_id"]
    prediction = {"generated_before_result": True, "research_only": True,
                  "strategy": "r1_explicit_reference", "betting_decision_status": "reference_only",
                  "predicted_ranking": [], "predicted_top3": [], "axis_horse_numbers": [],
                  "ranking_semantics": "quinella_pairs_and_top2_marginals_only", "run_id": result["run_id"],
                  "model": result["model"], "pairs": result["pairs"],
                  "runner_top2_marginals": result["runner_top2_marginals"],
                  "research_policy_candidate": result["research_policy_candidate"],
                  "research_policy_status": result["research_policy_status"],
                  "odds_horizon": result["odds_horizon"], "verification": result["verification"]}
    payload = {"prediction_id": prediction_id, "race_id": result["race_id"],
               "theory_version": "r1:spec150:explicit-reference:v1", "mode": "research_reference", "budget": 0,
               "created_at": result["scored_at"], "pre_race_snapshot": result["pre_race_snapshot"],
               "prediction_json": prediction, "prediction_tickets": []}
    store = build_analysis_store(ROOT / "data/db/analysis.sqlite")
    store.upsert_prediction_record(payload)
    saved = store.get_prediction_record(prediction_id)
    require(saved.race_id == result["race_id"] and digest(saved.prediction) == digest(prediction)
            and digest(saved.pre_race_snapshot) == digest(payload["pre_race_snapshot"])
            and len(saved.prediction_tickets) == 0, "r1_saved_reference_readback_mismatch")
    report = {"status": "passed", "prediction_id": prediction_id, "run_id": result["run_id"],
              "backend": "sqlserver", "readback_verified": True, "actual_tickets": 0,
              "pair_count": len(result["pairs"]), "saved_at": now.isoformat()}
    path = existing_run(result["run_id"]) / "sql-save-verification.json"
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    """CLI引数で1競走だけ推論し、保存結果または固定失敗理由を表示する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--course", required=True, choices=COURSES)
    parser.add_argument("--race-no", required=True, type=int)
    parser.add_argument("--meeting-no", required=True, type=int)
    parser.add_argument("--meeting-day", required=True, type=int)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(args.date, args.course, args.race_no, args.meeting_no, args.meeting_day)
        saved = save_reference(result) if args.save else None
        print(json.dumps({"status": "passed", "run_id": result["run_id"], "race_id": result["race_id"],
                          "top_probability_pairs": result["pairs"][:5], "research_policy_candidate": result["research_policy_candidate"],
                          "save": saved}, ensure_ascii=False, indent=2))
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("r1_cli_failed", 4, error_type=type(error).__name__)
        print(json.dumps({"status": "failed", "reason": safe.reason, "details": safe.details}, ensure_ascii=False))
        raise SystemExit(safe.exit_code) from None


if __name__ == "__main__":
    main()
