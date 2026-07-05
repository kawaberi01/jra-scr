import sqlite3

conn = sqlite3.connect("data/analysis.sqlite")

print("sample_race_results")
for row in conn.execute(
    """
    select race_id, race_name
    from race_results
    where race_id like '2025%'
    order by race_id
    limit 5
    """
):
    print("|".join("" if value is None else str(value) for value in row).encode("unicode_escape").decode("ascii"))

print("sample_result_entries")
for row in conn.execute(
    """
    select race_id, rank, horse_no, horse_name, jockey, finish_time
    from result_entries
    where race_id like '2025%'
    order by race_id, rank
    limit 12
    """
):
    print("|".join("" if value is None else str(value) for value in row).encode("unicode_escape").decode("ascii"))

print("sample_payouts")
for row in conn.execute(
    """
    select race_id, bet_type, combination, payout, popularity
    from payouts
    where race_id like '2025%'
    order by race_id, bet_type, combination
    limit 12
    """
):
    print("|".join("" if value is None else str(value) for value in row).encode("unicode_escape").decode("ascii"))
