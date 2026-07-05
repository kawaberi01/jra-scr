from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    conn.row_factory = sqlite3.Row

    print("May JRA races by date/course:")
    for row in conn.execute(
        """
        select race_date, substr(race_id,9,2) course_code, count(*) races
        from races
        where race_date between '2026-05-01' and '2026-05-31'
        group by race_date, substr(race_id,9,2)
        order by race_date, course_code
        """
    ):
        print(dict(row))

    checks = [
        (
            "Existing May netkeiba mappings",
            """
            select count(1)
            from netkeiba_race_mappings
            where race_date between '2026-05-01' and '2026-05-31'
            """,
        ),
        (
            "Existing May netkeiba results",
            """
            select count(distinct jra_race_id)
            from netkeiba_race_results
            where race_date between '2026-05-01' and '2026-05-31'
            """,
        ),
        (
            "JRA races without result entries",
            """
            select count(1)
            from races r
            left join result_entries e on e.race_id = r.race_id
            where r.race_date between '2026-01-01' and '2026-06-28'
              and e.race_id is null
            """,
        ),
    ]
    for label, sql in checks:
        print(f"{label}: {conn.execute(sql).fetchone()[0]}")

    print("JRA missing result/payout races:")
    for row in conn.execute(
        """
        select r.race_date, r.race_id, r.race_no, r.race_name,
               count(distinct e.horse_no) result_entries,
               count(distinct p.bet_type) payouts
        from races r
        left join result_entries e on e.race_id = r.race_id
        left join payouts p on p.race_id = r.race_id
        where r.race_date between '2026-01-01' and '2026-06-28'
        group by r.race_id
        having result_entries = 0 or payouts = 0
        order by r.race_date, r.race_id
        """
    ):
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    main()
