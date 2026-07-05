from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    conn.row_factory = sqlite3.Row

    orphaned = conn.execute(
        """
        select rr.netkeiba_race_id
        from netkeiba_race_results rr
        join netkeiba_race_mappings m on m.jra_race_id = rr.jra_race_id
        where m.race_date between '2025-01-01' and '2025-09-30'
          and rr.netkeiba_race_id != m.netkeiba_race_id
        """
    ).fetchall()
    race_ids = [str(row["netkeiba_race_id"]) for row in orphaned]
    print(f"orphaned_count={len(race_ids)}")
    if not race_ids:
        conn.close()
        return

    placeholders = ",".join("?" for _ in race_ids)
    conn.execute(f"delete from netkeiba_result_entries where netkeiba_race_id in ({placeholders})", race_ids)
    conn.execute(f"delete from netkeiba_payouts where netkeiba_race_id in ({placeholders})", race_ids)
    conn.execute(f"delete from netkeiba_odds_entries where netkeiba_race_id in ({placeholders})", race_ids)
    conn.execute(f"delete from netkeiba_race_results where netkeiba_race_id in ({placeholders})", race_ids)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
