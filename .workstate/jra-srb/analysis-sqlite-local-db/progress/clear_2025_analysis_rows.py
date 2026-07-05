import sqlite3

conn = sqlite3.connect("data/analysis.sqlite")
with conn:
    conn.execute("delete from result_entries where race_id like '2025%'")
    conn.execute("delete from payouts where race_id like '2025%'")
    conn.execute("delete from race_results where race_id like '2025%'")
    conn.execute("delete from runners where race_id like '2025%'")
    conn.execute("delete from races where race_date >= '2025-01-01' and race_date <= '2025-12-31'")

print("cleared_2025")
