import sqlite3

path = "data/analysis.sqlite"
with sqlite3.connect(path) as conn:
    tables = [
        "collection_runs",
        "races",
        "runners",
        "odds_snapshots",
        "odds_entries",
        "race_results",
        "result_entries",
        "payouts",
        "collection_errors",
    ]
    for table in tables:
        count = conn.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"{table}={count}")

    latest_run = conn.execute(
        """
        select run_id, from_date, to_date, courses_json, include_card, include_odds,
               include_results, odds_timing, status, created_at, finished_at
        from collection_runs
        order by created_at desc
        limit 1
        """
    ).fetchone()
    if latest_run is not None:
        print("latest_run=" + "|".join("" if value is None else str(value) for value in latest_run))

    errors = conn.execute(
        """
        select race_id, course, race_no, stage, error_type, error_message
        from collection_errors
        order by created_at desc
        limit 10
        """
    ).fetchall()
    for error in errors:
        print("error=" + "|".join("" if value is None else str(value) for value in error))
