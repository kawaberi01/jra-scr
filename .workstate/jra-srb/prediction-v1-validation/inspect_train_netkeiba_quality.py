from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    conn.row_factory = sqlite3.Row

    print("train rows with missing entries/payouts")
    for row in conn.execute(
        """
        select m.race_date,
               m.jra_race_id,
               m.netkeiba_race_id,
               rr.race_name,
               count(distinct e.rank || ':' || ifnull(e.horse_no, '')) as entry_count,
               count(distinct p.bet_type || ':' || p.combination) as payout_count
        from netkeiba_race_mappings m
        join netkeiba_race_results rr on rr.netkeiba_race_id = m.netkeiba_race_id
        left join netkeiba_result_entries e on e.netkeiba_race_id = rr.netkeiba_race_id
        left join netkeiba_payouts p on p.netkeiba_race_id = rr.netkeiba_race_id
        where m.race_date between '2025-01-01' and '2025-09-30'
        group by m.jra_race_id, m.netkeiba_race_id
        having entry_count = 0 or payout_count = 0
        order by m.race_date, m.jra_race_id
        limit 30
        """
    ):
        print(dict(row))

    print("train rows with mismatched saved date")
    for row in conn.execute(
        """
        select m.race_date as mapped_date,
               rr.race_date as saved_date,
               m.jra_race_id,
               m.netkeiba_race_id,
               rr.race_name
        from netkeiba_race_mappings m
        join netkeiba_race_results rr on rr.netkeiba_race_id = m.netkeiba_race_id
        where m.race_date between '2025-01-01' and '2025-09-30'
          and rr.race_date != m.race_date
        order by m.race_date, m.jra_race_id
        limit 30
        """
    ):
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    main()
