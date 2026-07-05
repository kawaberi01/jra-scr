from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
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
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

COURSE_NAME_TO_JP = {
    "sapporo": "札幌",
    "hakodate": "函館",
    "fukushima": "福島",
    "niigata": "新潟",
    "tokyo": "東京",
    "nakayama": "中山",
    "chukyo": "中京",
    "kyoto": "京都",
    "hanshin": "阪神",
    "kokura": "小倉",
}


@dataclass(frozen=True)
class MeetingStart:
    course: str
    start_date: date
    start_day_no: int


def load_rows(path: Path) -> list[MeetingStart]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return [
            MeetingStart(
                course=str(row["course"]).strip(),
                start_date=date.fromisoformat(str(row["start_date"]).strip()),
                start_day_no=int(str(row.get("start_day_no") or "1").strip()),
            )
            for row in reader
        ]


def parse_title(title: str) -> tuple[str | None, str | None]:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+([^\s0-9]+)\d+R", title)
    if not match:
        return None, None
    found_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return found_date, match.group(4)


def discover_one(
    client: httpx.Client,
    row: MeetingStart,
    max_meeting_no: int,
    max_day_no: int,
    sleep_seconds: float,
) -> tuple[int | None, int | None, str | None]:
    course_code = COURSE_NAME_TO_CODE[row.course]
    expected_date = row.start_date.isoformat()
    expected_course = COURSE_NAME_TO_JP[row.course]
    for meeting_no in range(1, max_meeting_no + 1):
        for day_no in range(1, max_day_no + 1):
            race_id = f"{row.start_date.year}{course_code}{meeting_no:02d}{day_no:02d}01"
            response = client.get(
                "https://race.sp.netkeiba.com/"
                f"?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
            )
            title_match = re.search(r"<title>(.*?)</title>", response.text, re.S)
            title = (title_match.group(1) if title_match else "").strip()
            found_date, found_course = parse_title(title)
            if found_date == expected_date and found_course == expected_course:
                return meeting_no, day_no, race_id
            time.sleep(sleep_seconds)
    return None, None, None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    max_meeting_no = int(sys.argv[3]) if len(sys.argv) >= 4 else 6
    max_day_no = int(sys.argv[4]) if len(sys.argv) >= 5 else 12
    sleep_seconds = float(sys.argv[5]) if len(sys.argv) >= 6 else 0.3

    rows = load_rows(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "course",
                "start_date",
                "expected_start_day_no",
                "discovered_meeting_no",
                "discovered_day_no",
                "sample_race_id",
            ]
        )
        with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
            for row in rows:
                meeting_no, day_no, race_id = discover_one(
                    client=client,
                    row=row,
                    max_meeting_no=max_meeting_no,
                    max_day_no=max_day_no,
                    sleep_seconds=sleep_seconds,
                )
                writer.writerow(
                    [
                        row.course,
                        row.start_date.isoformat(),
                        row.start_day_no,
                        meeting_no or "",
                        day_no or "",
                        race_id or "",
                    ]
                )
                print(
                    f"{row.course},{row.start_date.isoformat()},{row.start_day_no},"
                    f"{meeting_no or ''},{day_no or ''},{race_id or ''}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
