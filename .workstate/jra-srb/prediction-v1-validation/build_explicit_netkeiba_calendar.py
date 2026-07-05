from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import re
import sqlite3
import sys
import time

import httpx

from jra_srb.service import COURSE_NAME_TO_CODE


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def load_discovered(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_jra_dates() -> set[tuple[str, str]]:
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
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    sleep_seconds = float(sys.argv[3]) if len(sys.argv) >= 4 else 0.1

    discovered = load_discovered(input_path)
    jra_dates = load_jra_dates()
    unique_prefixes: dict[tuple[str, str], tuple[str, int]] = {}
    for row in discovered:
        course = str(row["course"]).strip()
        meeting_no = int(str(row["discovered_meeting_no"]).strip())
        course_code = COURSE_NAME_TO_CODE[course]
        unique_prefixes[(course, str(meeting_no))] = (course_code, meeting_no)

    rows: list[tuple[str, int, str, int]] = []
    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for (course, _), (course_code, meeting_no) in sorted(unique_prefixes.items()):
            for day_no in range(1, 13):
                race_id = f"2025{course_code}{meeting_no:02d}{day_no:02d}01"
                response = client.get(
                    "https://race.sp.netkeiba.com/"
                    f"?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
                )
                title_match = re.search(r"<title>(.*?)</title>", response.text, re.S)
                title = (title_match.group(1) if title_match else "").strip()
                race_date = parse_title_date(title)
                if race_date is None:
                    time.sleep(sleep_seconds)
                    continue
                if (race_date, course_code) in jra_dates:
                    rows.append((course, meeting_no, race_date, day_no))
                    print(f"{course},{meeting_no},{race_date},{day_no}", flush=True)
                time.sleep(sleep_seconds)

    rows.sort(key=lambda item: (item[0], item[2], item[3]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["course", "meeting_no", "start_date", "start_day_no"])
        for course, meeting_no, race_date, day_no in rows:
            writer.writerow([course, meeting_no, race_date, day_no])


if __name__ == "__main__":
    main()
