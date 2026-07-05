import sqlite3

DB_PATH = "data/analysis.sqlite"

with sqlite3.connect(DB_PATH) as conn:
    counts = {}
    for table in [
        "collection_runs",
        "races",
        "runners",
        "odds_snapshots",
        "odds_entries",
        "race_results",
        "result_entries",
        "payouts",
        "collection_errors",
    ]:
        counts[table] = conn.execute(f"select count(*) from {table}").fetchone()[0]

    latest_run = conn.execute(
        """
        select run_id, status, created_at, finished_at
        from collection_runs
        order by created_at desc
        limit 1
        """
    ).fetchone()

    suspicious = conn.execute(
        """
        select race_id, horse_no, horse_name, jockey, trainer
        from runners
        where jockey in ('▲', '△', '☆') or jockey is null or jockey = ''
        order by race_id, horse_no
        """
    ).fetchall()

    apprentice = conn.execute(
        """
        select race_id, horse_no, horse_name, jockey, trainer
        from runners
        where jockey like '▲%' or jockey like '△%' or jockey like '☆%'
        order by race_id, horse_no
        limit 20
        """
    ).fetchall()

    sample_results = conn.execute(
        """
        select race_id, rank, horse_no, horse_name, jockey
        from result_entries
        order by race_id, rank
        limit 12
        """
    ).fetchall()

    latest_errors = conn.execute(
        """
        select race_id, course, race_no, stage, error_type, error_message
        from collection_errors
        order by created_at desc
        limit 10
        """
    ).fetchall()

for key, value in counts.items():
    print(f"{key}={value}")

if latest_run:
    print("latest_run=" + "|".join("" if x is None else str(x) for x in latest_run))

print(f"suspicious_jockey_rows={len(suspicious)}")
for row in suspicious[:20]:
    print("suspicious=" + "|".join("" if x is None else str(x) for x in row))

print(f"apprentice_rows={len(apprentice)}")
for row in apprentice:
    print("apprentice=" + "|".join("" if x is None else str(x) for x in row))

print("sample_results_start")
for row in sample_results:
    print("result=" + "|".join("" if x is None else str(x) for x in row))

print("latest_errors_start")
for row in latest_errors:
    print("error=" + "|".join("" if x is None else str(x) for x in row))
