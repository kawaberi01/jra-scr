from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    conn.row_factory = sqlite3.Row

    print("mapped races without matching parent row by netkeiba_race_id")
    for row in conn.execute(
        """
        select m.race_date, m.jra_race_id, m.netkeiba_race_id
        from netkeiba_race_mappings m
        left join netkeiba_race_results rr on rr.netkeiba_race_id = m.netkeiba_race_id
        where m.race_date between '2025-01-01' and '2025-09-30'
          and rr.netkeiba_race_id is null
        order by m.race_date, m.jra_race_id
        limit 30
        """
    ):
        print(dict(row))

    print("mapped races where parent row jra_race_id is null")
    for row in conn.execute(
        """
        select m.race_date, m.jra_race_id, m.netkeiba_race_id, rr.race_date as saved_date, rr.jra_race_id as parent_jra_race_id
        from netkeiba_race_mappings m
        join netkeiba_race_results rr on rr.netkeiba_race_id = m.netkeiba_race_id
        where m.race_date between '2025-01-01' and '2025-09-30'
          and (rr.jra_race_id is null or rr.jra_race_id = '')
        order by m.race_date, m.jra_race_id
        limit 30
        """
    ):
        print(dict(row))

    print("duplicate parent jra_race_id rows")
    for row in conn.execute(
        """
        select rr.jra_race_id, count(*) as cnt
        from netkeiba_race_results rr
        where rr.race_date between '2025-01-01' and '2025-09-30'
          and rr.jra_race_id is not null
          and rr.jra_race_id != ''
        group by rr.jra_race_id
        having cnt > 1
        order by cnt desc, rr.jra_race_id
        limit 30
        """
    ):
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    main()
