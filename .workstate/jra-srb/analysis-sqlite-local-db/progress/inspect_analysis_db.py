import sqlite3
from pathlib import Path

path = Path("data/analysis.sqlite")
print(f"exists={path.exists()}")
print(f"path={path}")
with sqlite3.connect(path) as conn:
    rows = conn.execute(
        "select name from sqlite_master where type = 'table' order by name"
    ).fetchall()
print(f"tables={len(rows)}")
for row in rows:
    print(row[0])
