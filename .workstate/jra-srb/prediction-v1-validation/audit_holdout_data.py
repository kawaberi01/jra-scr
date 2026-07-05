from __future__ import annotations

from datetime import date
import sqlite3


DB_PATH = "data/analysis.sqlite"
FROM_DATE = "2026-01-01"
TO_DATE = "2026-06-28"


def expected_months(from_date: str, to_date: str) -> list[str]:
    start = date.fromisoformat(from_date).replace(day=1)
    end = date.fromisoformat(to_date).replace(day=1)
    months = []
    current = start
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)
    return months


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("tables")
    for row in cur.execute("select name from sqlite_master where type='table' order by name"):
        print(f"- {row['name']}")

    print("holdout race coverage")
    coverage = cur.execute(
        """
        select count(distinct r.race_id) races,
               count(ru.race_id) runner_rows,
               count(re.race_id) result_rows,
               min(r.race_date) min_date,
               max(r.race_date) max_date
        from races r
        left join runners ru on ru.race_id = r.race_id
        left join result_entries re on re.race_id = ru.race_id and re.horse_no = ru.horse_no
        where r.race_date between ? and ?
        """,
        (FROM_DATE, TO_DATE),
    ).fetchone()
    print(dict(coverage))

    print("by month")
    month_rows_by_key = {}
    for row in cur.execute(
        """
        select substr(r.race_date, 1, 7) ym,
               count(distinct r.race_id) races,
               count(ru.race_id) runners,
               count(re.race_id) results
        from races r
        left join runners ru on ru.race_id = r.race_id
        left join result_entries re on re.race_id = ru.race_id and re.horse_no = ru.horse_no
        where r.race_date between ? and ?
        group by substr(r.race_date, 1, 7)
        order by ym
        """,
        (FROM_DATE, TO_DATE),
    ):
        month_row = dict(row)
        month_rows_by_key[month_row["ym"]] = month_row

    month_rows = []
    for ym in expected_months(FROM_DATE, TO_DATE):
        month_row = month_rows_by_key.get(ym) or {"ym": ym, "races": 0, "runners": 0, "results": 0}
        month_rows.append(month_row)
        print(month_row)

    print("netkeiba mapping/result coverage")
    netkeiba_coverage = cur.execute(
        """
        select count(distinct r.race_id) races,
               count(distinct m.jra_race_id) mapped,
               count(distinct nrr.netkeiba_race_id) nk_result_parent,
               count(distinct nre.netkeiba_race_id) nk_entries_races,
               count(distinct np.netkeiba_race_id) nk_payout_races
        from races r
        left join netkeiba_race_mappings m
          on m.jra_race_id = r.race_id and m.netkeiba_race_id is not null and m.netkeiba_race_id != ''
        left join netkeiba_race_results nrr on nrr.netkeiba_race_id = m.netkeiba_race_id
        left join netkeiba_result_entries nre on nre.netkeiba_race_id = m.netkeiba_race_id
        left join netkeiba_payouts np on np.netkeiba_race_id = m.netkeiba_race_id
        where r.race_date between ? and ?
        """,
        (FROM_DATE, TO_DATE),
    ).fetchone()
    print(dict(netkeiba_coverage))

    missing_jra_months = [
        row["ym"]
        for row in month_rows
        if row["races"] <= 0 or row["runners"] <= 0 or row["results"] <= 0
    ]
    race_count = int(coverage["races"] or 0)
    runner_rows = int(coverage["runner_rows"] or 0)
    result_rows = int(coverage["result_rows"] or 0)
    mapped = int(netkeiba_coverage["mapped"] or 0)
    nk_entries = int(netkeiba_coverage["nk_entries_races"] or 0)
    nk_payouts = int(netkeiba_coverage["nk_payout_races"] or 0)
    audit_ok = (
        race_count > 0
        and runner_rows > 0
        and result_rows > 0
        and not missing_jra_months
        and mapped == race_count
        and nk_entries == race_count
        and nk_payouts == race_count
    )
    print("audit gates")
    print(f"jra_months_complete={not missing_jra_months}")
    print(f"missing_jra_months={','.join(missing_jra_months) if missing_jra_months else '-'}")
    print(f"netkeiba_mapping_complete={mapped == race_count}")
    print(f"netkeiba_results_complete={nk_entries == race_count}")
    print(f"netkeiba_payouts_complete={nk_payouts == race_count}")
    print(f"AUDIT_STATUS={'PASS' if audit_ok else 'FAIL'}")

    print("sample mappings")
    for row in cur.execute(
        """
        select r.race_date, r.race_id, r.race_no, m.netkeiba_race_id
        from races r
        left join netkeiba_race_mappings m on m.jra_race_id = r.race_id
        where r.race_date between ? and ?
        order by r.race_date, r.race_id
        limit 20
        """,
        (FROM_DATE, TO_DATE),
    ):
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    main()
