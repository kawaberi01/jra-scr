from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from jra_srb.analysis_store import AnalysisSQLiteStore


DB_PATH = Path("data/db/analysis.sqlite")


def main() -> None:
    store = AnalysisSQLiteStore(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "select prediction_id, race_id, evaluation_json from evaluations "
            "where race_id like '20260711%' order by race_id"
        ).fetchall()
    report = []
    for prediction_id, race_id, evaluation_json in rows:
        evaluation = json.loads(evaluation_json)
        predicted = [str(item.get("horse_no")) for item in evaluation["predicted_top3"] if item.get("horse_no")]
        actual = [str(item.get("horse_no")) for item in evaluation["actual_top3"] if item.get("horse_no")]
        overlap = len(set(predicted) & set(actual))
        winner_hit = bool(actual and actual[0] in predicted)
        ticket_hit = bool(evaluation["ticket_review"]["total_payout"])
        lesson = _lesson(winner_hit, ticket_hit, overlap)
        saved = store.evaluate_prediction_record(
            {
                "prediction_id": prediction_id,
                "review": {
                    "post_review_version": "jra-live-review-v1",
                    "predicted_actual_top3_overlap": overlap,
                    "winner_in_predicted_top3": winner_hit,
                    "ticket_hit": ticket_hit,
                    "lesson": lesson,
                },
                "review_notes": [
                    "公開Ω指数・単勝・近走時計の単純加点で順位を作成した。",
                    "ワイド組合せオッズ未取得のため、買い目は上位3頭から固定2点で作成した。",
                    lesson,
                ],
            }
        )
        report.append({"race_id": race_id, "overlap": overlap, "winner_hit": winner_hit, "ticket_hit": ticket_hit, "lesson": lesson, "saved": saved})
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _lesson(winner_hit: bool, ticket_hit: bool, overlap: int) -> str:
    if ticket_hit:
        return "上位評価と固定ワイドの組合せが機能した。再現性確認のため組合せオッズも保存対象にする。"
    if winner_hit:
        return "勝ち馬は上位評価できたが、固定ワイド2点が相手を取り切れなかった。順位評価と券種選択を分離して見直す。"
    if overlap:
        return "一部の上位馬は拾えたが、勝ち馬を上位3頭へ入れられなかった。単純加点の重みを過去データで検証する。"
    return "上位3頭と実際の上位が一致しなかった。公開指標の単純加点だけでは不足で、条件別の校正が必要。"


if __name__ == "__main__":
    main()
