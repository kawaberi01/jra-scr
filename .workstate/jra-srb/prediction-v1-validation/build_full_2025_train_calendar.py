from __future__ import annotations

import csv
import re
import sqlite3
import sys
import time

import httpx

from jra_srb.service import COURSE_CODE_TO_NAME


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def load_jra_course_dates() -> set[tuple[str, str]]:
    conn = sqlite3.connect("data/analysis.sqlite")
    rows = conn.execute(
        """
        select race_date, substr(race_id, 9, 2) as course_code
        from races
        where race_date between '2025-01-01' and '2025-09-30'
        group by race_date, substr(race_id, 9, 2)
        """
    ).fetchall()
    conn.close()
    return {(str(row[0]), str(row[1])) for row in rows}


def parse_title_date(title: str) -> str | None:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    output_path = sys.argv[1]
    sleep_seconds = float(sys.argv[2]) if len(sys.argv) >= 3 else 0.05
    max_meeting_no = int(sys.argv[3]) if len(sys.argv) >= 4 else 6
    max_day_no = int(sys.argv[4]) if len(sys.argv) >= 5 else 12

    jra_dates = load_jra_course_dates()
    rows: list[tuple[str, int, str, int, str]] = []

    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for course_code, course in sorted(COURSE_CODE_TO_NAME.items()):
            for meeting_no in range(1, max_meeting_no + 1):
                for day_no in range(1, max_day_no + 1):
                    race_id = f"2025{course_code}{meeting_no:02d}{day_no:02d}01"
                    response = client.get(
                        "https://race.sp.netkeiba.com/"
                        f"?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
                    )
                    title_match = re.search(r"<title>(.*?)</title>", response.text, re.S)
                    title = (title_match.group(1) if title_match else "").strip()
                    race_date = parse_title_date(title)
                    if race_date is not None and (race_date, course_code) in jra_dates:
                        rows.append((course, meeting_no, race_date, day_no, race_id))
                        print(f"{course},{meeting_no},{race_date},{day_no},{race_id}", flush=True)
                    time.sleep(sleep_seconds)

    unique = {}
    for course, meeting_no, race_date, day_no, race_id in rows:
        unique[(course, race_date)] = (meeting_no, day_no, race_id)

    with open(output_path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["course", "meeting_no", "start_date", "start_day_no", "sample_race_id"])
        for (course, race_date), (meeting_no, day_no, race_id) in sorted(unique.items()):
            writer.writerow([course, meeting_no, race_date, day_no, race_id])


if __name__ == "__main__":
    main()
