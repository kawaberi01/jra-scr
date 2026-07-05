from __future__ import annotations

import sqlite3
import sys


FROM_DATE = "2025-01-01"
TO_DATE = "2025-09-30"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    conn.row_factory = sqlite3.Row

    print(f"train_period={FROM_DATE}..{TO_DATE}")
    print("by_month")
    for row in conn.execute(
        """
        with jra as (
            select substr(race_date, 1, 7) as ym, count(*) as races
            from races
            where race_date between ? and ?
            group by substr(race_date, 1, 7)
        ),
        mapped as (
            select substr(race_date, 1, 7) as ym, count(*) as mapped
            from netkeiba_race_mappings
            where race_date between ? and ?
              and netkeiba_race_id is not null
              and netkeiba_race_id != ''
            group by substr(race_date, 1, 7)
        ),
        nk_results as (
            select substr(race_date, 1, 7) as ym, count(distinct jra_race_id) as result_races
            from netkeiba_race_results
            where race_date between ? and ?
            group by substr(race_date, 1, 7)
        ),
        nk_payouts as (
            select substr(rr.race_date, 1, 7) as ym, count(distinct rr.jra_race_id) as payout_races
            from netkeiba_race_results rr
            join netkeiba_payouts p on p.netkeiba_race_id = rr.netkeiba_race_id
            where rr.race_date between ? and ?
            group by substr(rr.race_date, 1, 7)
        )
        select jra.ym,
               jra.races,
               coalesce(mapped.mapped, 0) as mapped,
               coalesce(nk_results.result_races, 0) as result_races,
               coalesce(nk_payouts.payout_races, 0) as payout_races
        from jra
        left join mapped on mapped.ym = jra.ym
        left join nk_results on nk_results.ym = jra.ym
        left join nk_payouts on nk_payouts.ym = jra.ym
        order by jra.ym
        """,
        (FROM_DATE, TO_DATE, FROM_DATE, TO_DATE, FROM_DATE, TO_DATE, FROM_DATE, TO_DATE),
    ):
        print(dict(row))

    summary = conn.execute(
        """
        with jra as (
            select count(*) as races
            from races
            where race_date between ? and ?
        ),
        mapped as (
            select count(*) as mapped
            from netkeiba_race_mappings
            where race_date between ? and ?
              and netkeiba_race_id is not null
              and netkeiba_race_id != ''
        ),
        nk_results as (
            select count(distinct jra_race_id) as result_races
            from netkeiba_race_results
            where race_date between ? and ?
        ),
        nk_payouts as (
            select count(distinct rr.jra_race_id) as payout_races
            from netkeiba_race_results rr
            join netkeiba_payouts p on p.netkeiba_race_id = rr.netkeiba_race_id
            where rr.race_date between ? and ?
        )
        select jra.races, mapped.mapped, nk_results.result_races, nk_payouts.payout_races
        from jra, mapped, nk_results, nk_payouts
        """,
        (FROM_DATE, TO_DATE, FROM_DATE, TO_DATE, FROM_DATE, TO_DATE, FROM_DATE, TO_DATE),
    ).fetchone()
    print("summary")
    print(dict(summary))
    conn.close()


if __name__ == "__main__":
    main()
