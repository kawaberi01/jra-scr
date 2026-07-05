import sqlite3

conn = sqlite3.connect("data/analysis.sqlite")

latest_run = conn.execute(
    """
    select run_id, status, created_at, finished_at
    from collection_runs
    order by created_at desc
    limit 1
    """
).fetchone()

print("latest_run=" + "|".join("" if v is None else str(v) for v in latest_run))

for label, sql in [
    (
        "latest_run_meta",
        """
        select from_date, to_date, courses_json, include_card, include_odds, include_results, status
        from collection_runs
        order by created_at desc
        limit 1
        """,
    ),
    ("races_2025", "select count(*) from races where race_date >= '2025-01-01' and race_date <= '2025-12-31'"),
    ("race_results_2025", "select count(*) from race_results where race_id like '2025%'"),
    ("result_entries_2025", "select count(*) from result_entries where race_id like '2025%'"),
    ("payouts_2025", "select count(*) from payouts where race_id like '2025%'"),
    ("runners_2025", "select count(*) from runners where race_id like '2025%'"),
    ("days_2025", "select count(distinct race_date) from races where race_date >= '2025-01-01' and race_date <= '2025-12-31'"),
]:
    row = conn.execute(sql).fetchone()
    print(f"{label}=" + "|".join("" if v is None else str(v) for v in row))

latest_run_id = latest_run[0]
for label, sql in [
    ("latest_run_errors", "select count(*) from collection_errors where run_id = ?"),
]:
    row = conn.execute(sql, (latest_run_id,)).fetchone()
    print(f"{label}=" + "|".join("" if v is None else str(v) for v in row))

for row in conn.execute(
    """
    select race_id, course, race_no, stage, error_type, error_message
    from collection_errors
    where run_id = ?
    order by race_id, stage
    limit 30
    """,
    (latest_run_id,),
):
    print("latest_error=" + "|".join("" if v is None else str(v) for v in row))
