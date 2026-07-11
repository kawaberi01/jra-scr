from __future__ import annotations

import json
from pathlib import Path
import sqlite3


DB_PATH = Path("data/db/analysis.sqlite")


def main() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        report = {
            "integrity_check": conn.execute("pragma integrity_check").fetchone()[0],
            "predictions": _scalar(conn, "select count(*) from predictions where race_id like '20260711%'"),
            "prediction_tickets": _scalar(conn, "select count(*) from prediction_tickets where race_id like '20260711%'"),
            "results": _scalar(conn, "select count(*) from race_results where race_id like '20260711%'"),
            "result_entries": _scalar(conn, "select count(*) from result_entries where race_id like '20260711%'"),
            "payouts": _scalar(conn, "select count(*) from payouts where race_id like '20260711%'"),
            "evaluations": _scalar(conn, "select count(*) from evaluations where race_id like '20260711%'"),
            "duplicate_predictions_by_race": conn.execute(
                "select race_id, count(*) from predictions where race_id like '20260711%' group by race_id having count(*) > 1"
            ).fetchall(),
            "prediction_without_result": [row[0] for row in conn.execute(
                "select distinct p.race_id from predictions p left join race_results r on r.race_id=p.race_id "
                "where p.race_id like '20260711%' and r.race_id is null order by p.race_id"
            )],
            "result_without_payout": [row[0] for row in conn.execute(
                "select r.race_id from race_results r left join payouts p on p.race_id=r.race_id "
                "where r.race_id like '20260711%' group by r.race_id having count(p.race_id)=0"
            )],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _scalar(conn: sqlite3.Connection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


if __name__ == "__main__":
    main()
