from __future__ import annotations

import json
from pathlib import Path
import sqlite3


DB = Path("data/db/analysis.sqlite")
OUT = Path("data/live/2026-07-11-retrospective.json")


def main() -> None:
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        summary = dict(conn.execute(
            "select count(*) races, sum(hit) hit_races, sum(total_bet) total_bet, sum(total_payout) total_payout "
            "from evaluations where race_id like '20260711%'"
        ).fetchone())
        summary["return_rate"] = round(summary["total_payout"] / summary["total_bet"], 4) if summary["total_bet"] else None
        summary["ticket_hits"] = conn.execute(
            "select count(*) from evaluation_ticket_results et join evaluations e on e.evaluation_id=et.evaluation_id "
            "where e.race_id like '20260711%' and et.hit=1"
        ).fetchone()[0]
        rows = conn.execute(
            """
            select e.race_id, e.hit, e.total_bet, e.total_payout, e.return_rate,
                   p.prediction_json, e.evaluation_json
            from evaluations e join predictions p on p.prediction_id=e.prediction_id
            where e.race_id like '20260711%' order by e.race_id
            """
        ).fetchall()
        races = []
        for row in rows:
            predicted = json.loads(row["prediction_json"])
            evaluation = json.loads(row["evaluation_json"])
            races.append({
                "race_id": row["race_id"], "hit": bool(row["hit"]), "total_bet": row["total_bet"],
                "total_payout": row["total_payout"], "return_rate": row["return_rate"],
                "predicted_top3": predicted.get("predicted_top3", []),
                "actual_top3": evaluation.get("actual_top3", []),
                "review": evaluation.get("review_summary", {}),
            })
    report = {"summary": summary, "races": races, "eleven_races": [r for r in races if r["race_id"][-2:] == "11"]}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
