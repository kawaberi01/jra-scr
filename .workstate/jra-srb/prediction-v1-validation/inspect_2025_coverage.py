from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    print("JRA months 2025")
    for row in conn.execute(
        """
        select substr(race_date, 1, 7) as ym, count(*)
        from races
        where race_date between '2025-01-01' and '2025-12-31'
        group by substr(race_date, 1, 7)
        order by ym
        """
    ):
        print(*row)
    print("netkeiba months 2025")
    for row in conn.execute(
        """
        select substr(race_date, 1, 7) as ym, count(distinct jra_race_id)
        from netkeiba_race_results
        where race_date between '2025-01-01' and '2025-12-31'
        group by substr(race_date, 1, 7)
        order by ym
        """
    ):
        print(*row)
    conn.close()


if __name__ == "__main__":
    main()
