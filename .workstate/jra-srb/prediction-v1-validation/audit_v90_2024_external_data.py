from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def scalar(conn: sqlite3.Connection, query: str, params: tuple[str, str]) -> int:
    return int(conn.execute(query, params).fetchone()[0] or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the fixed 2024 Jul-Aug v90 external-evaluation inputs.")
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--from-date", default="2024-07-01")
    parser.add_argument("--to-date", default="2024-08-31")
    args = parser.parse_args()
    dates = (args.from_date, args.to_date)

    with sqlite3.connect(args.db) as conn:
        races = scalar(conn, "select count(*) from races where race_date between ? and ?", dates)
        official_results = scalar(
            conn,
            """select count(*) from races r join race_results rr on rr.race_id=r.race_id
               where r.race_date between ? and ?""",
            dates,
        )
        runners = scalar(
            conn,
            """select count(*) from runners ru join races r on r.race_id=ru.race_id
               where r.race_date between ? and ?""",
            dates,
        )
        incomplete_runners = scalar(
            conn,
            """select count(*) from races r join race_results rr on rr.race_id=r.race_id
               where r.race_date between ? and ?
                 and not exists (select 1 from runners ru where ru.race_id=r.race_id)""",
            dates,
        )
        mapped = scalar(
            conn,
            """select count(*) from races r join race_results rr on rr.race_id=r.race_id
               join netkeiba_race_mappings m on m.jra_race_id=r.race_id
               where r.race_date between ? and ? and m.netkeiba_race_id != ''""",
            dates,
        )
        parent = scalar(
            conn,
            """select count(*) from races r join race_results rr on rr.race_id=r.race_id
               join netkeiba_race_mappings m on m.jra_race_id=r.race_id
               join netkeiba_race_results n on n.netkeiba_race_id=m.netkeiba_race_id
               where r.race_date between ? and ?""",
            dates,
        )
        entries = scalar(
            conn,
            """select count(distinct r.race_id) from races r join race_results rr on rr.race_id=r.race_id
               join netkeiba_race_mappings m on m.jra_race_id=r.race_id
               join netkeiba_result_entries e on e.netkeiba_race_id=m.netkeiba_race_id
               where r.race_date between ? and ?""",
            dates,
        )
        payouts = scalar(
            conn,
            """select count(distinct r.race_id) from races r join race_results rr on rr.race_id=r.race_id
               join netkeiba_race_mappings m on m.jra_race_id=r.race_id
               join netkeiba_payouts p on p.netkeiba_race_id=m.netkeiba_race_id
               where r.race_date between ? and ?""",
            dates,
        )
        mapping_metadata_mismatches = scalar(
            conn,
            """select count(*) from races r join race_results rr on rr.race_id=r.race_id
               join netkeiba_race_mappings m on m.jra_race_id=r.race_id
               where r.race_date between ? and ?
                 and (m.race_date != r.race_date or m.course != r.course or m.race_no != r.race_no)""",
            dates,
        )

    values = {
        "races": races,
        "official_results": official_results,
        "runners": runners,
        "official_result_races_without_runners": incomplete_runners,
        "mapped": mapped,
        "netkeiba_parent": parent,
        "netkeiba_entries": entries,
        "netkeiba_payouts": payouts,
        "mapping_metadata_mismatches": mapping_metadata_mismatches,
    }
    for key, value in values.items():
        print(f"{key}={value}")

    passed = (
        official_results > 0
        and runners > 0
        and incomplete_runners == 0
        and mapped == official_results
        and parent == official_results
        and entries == official_results
        and payouts == official_results
        and mapping_metadata_mismatches == 0
    )
    print(f"AUDIT_STATUS={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
