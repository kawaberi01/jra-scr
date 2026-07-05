import sqlite3

conn = sqlite3.connect("data/analysis.sqlite")

latest = conn.execute(
    "select run_id from collection_runs order by created_at desc limit 1"
).fetchone()[0]

print(f"latest_run_id={latest}")
print(
    "latest_run_error_count="
    + str(
        conn.execute(
            "select count(*) from collection_errors where run_id = ?",
            (latest,),
        ).fetchone()[0]
    )
)
print(
    "orphan_marker_count="
    + str(
        conn.execute(
            "select count(*) from runners where jockey in ('▲', '△', '☆') or jockey is null or jockey = ''"
        ).fetchone()[0]
    )
)

for row in conn.execute(
    """
    select race_id, stage, error_type, error_message
    from collection_errors
    where run_id = ?
    order by race_id, stage
    """,
    (latest,),
):
    print("latest_error=" + "|".join("" if v is None else str(v) for v in row))
