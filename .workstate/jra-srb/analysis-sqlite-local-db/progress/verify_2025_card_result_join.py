import sqlite3

conn = sqlite3.connect("data/analysis.sqlite")
conn.row_factory = sqlite3.Row

checks = [
    ("races_2025", "select count(1) from races where race_date between '2025-01-01' and '2025-12-31'"),
    ("race_results_2025", "select count(1) from race_results where race_id like '2025%'"),
    ("result_entries_2025", "select count(1) from result_entries where race_id like '2025%'"),
    ("payouts_2025", "select count(1) from payouts where race_id like '2025%'"),
    ("runners_2025", "select count(1) from runners where race_id like '2025%'"),
    (
        "races_with_runners_2025",
        "select count(1) from (select race_id from runners where race_id like '2025%' group by race_id)",
    ),
    (
        "result_runner_join_rows_2025",
        """
        select count(1)
        from result_entries re
        join runners ru on ru.race_id = re.race_id and ru.horse_no = re.horse_no
        where re.race_id like '2025%'
        """,
    ),
    (
        "payout_runner_race_join_rows_2025",
        """
        select count(1)
        from payouts p
        join runners ru on ru.race_id = p.race_id
        where p.race_id like '2025%'
        """,
    ),
]

for label, sql in checks:
    print(f"{label}={conn.execute(sql).fetchone()[0]}")

latest_run = conn.execute(
    """
    select run_id, status, from_date, to_date, include_card, include_odds, include_results
    from collection_runs
    order by created_at desc
    limit 1
    """
).fetchone()
print("latest_run=" + "|".join(str(value) for value in latest_run))
print(
    "latest_run_errors="
    + str(conn.execute("select count(1) from collection_errors where run_id = ?", (latest_run["run_id"],)).fetchone()[0])
)

for row in conn.execute(
    """
    select re.race_id, r.race_date, r.course, r.race_no,
           re.rank, re.horse_no, re.horse_name as result_horse_name,
           ru.horse_name as runner_horse_name, ru.jockey, ru.trainer,
           p.bet_type, p.combination, p.payout
    from result_entries re
    join races r on r.race_id = re.race_id
    join runners ru on ru.race_id = re.race_id and ru.horse_no = re.horse_no
    left join payouts p on p.race_id = re.race_id
    where re.race_id like '2025%' and re.rank in (1, 2, 3)
    group by re.race_id, re.rank
    order by re.race_id, re.rank
    limit 10
    """
):
    print("sample=" + "|".join("" if value is None else str(value) for value in row))
