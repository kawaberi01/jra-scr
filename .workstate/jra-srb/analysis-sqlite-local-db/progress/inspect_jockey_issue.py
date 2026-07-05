import sqlite3

with sqlite3.connect("data/analysis.sqlite") as conn:
    rows = conn.execute(
        """
        select race_id, horse_no, horse_name, sex_age, weight_carried, jockey, trainer
        from runners
        where jockey = '▲' or jockey = '△' or jockey = '☆' or jockey is null
        order by race_id, horse_no
        """
    ).fetchall()

for row in rows:
    print(row)

print(f"rows={len(rows)}")
