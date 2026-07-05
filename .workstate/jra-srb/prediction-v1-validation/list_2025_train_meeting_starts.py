from __future__ import annotations

import sqlite3
import sys
from datetime import date


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("data/analysis.sqlite")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        select race_date, substr(race_id, 9, 2) as course_code
        from races
        where race_date between '2025-01-01' and '2025-09-30'
        group by race_date, substr(race_id, 9, 2)
        order by course_code, race_date
        """
    ).fetchall()
    conn.close()

    by_course: dict[str, list[date]] = {}
    for row in rows:
        by_course.setdefault(row["course_code"], []).append(date.fromisoformat(row["race_date"]))

    for course_code, dates in sorted(by_course.items()):
        print(f"[{course_code}]")
        prev: date | None = None
        meeting_no = 0
        for current in dates:
            if prev is None or (current - prev).days > 6:
                meeting_no += 1
                print(f"start {meeting_no:02d} {current.isoformat()}")
            prev = current


if __name__ == "__main__":
    main()
