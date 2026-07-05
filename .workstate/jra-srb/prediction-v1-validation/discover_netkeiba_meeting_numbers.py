from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

import httpx
from bs4 import BeautifulSoup

from jra_srb.service import COURSE_NAME_TO_CODE


NETKEIBA_HEADERS = {
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
class MeetingRow:
    course: str
    start_date: date
    start_day_no: int


def load_rows(path: Path) -> list[MeetingRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = []
        for row in reader:
            rows.append(
                MeetingRow(
                    course=str(row["course"]).strip(),
                    start_date=date.fromisoformat(str(row["start_date"]).strip()),
                    start_day_no=int(str(row.get("start_day_no") or "1").strip()),
                )
            )
    return rows


def parse_meta_date_course(html: str) -> tuple[str | None, str | None, int]:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[name="description"]')
    meta_text = meta.get("content") if meta and meta.get("content") else ""
    result_rows = len(soup.select("#All_Result_Table tr"))
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+([^0-9\s]+)(\d{1,2})R", meta_text)
    if not match:
        return None, None, result_rows
    found_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    found_course = match.group(4)
    return found_date, found_course, result_rows


def discover_meeting_no(
    client: httpx.Client,
    row: MeetingRow,
    max_meeting_no: int = 12,
    max_day_no: int = 12,
) -> tuple[int | None, int | None, str | None]:
    course_code = COURSE_NAME_TO_CODE[row.course]
    expected_date = row.start_date.isoformat()
    expected_course = COURSE_NAME_TO_JP[row.course]
    for meeting_no in range(1, max_meeting_no + 1):
        for day_no in range(1, max_day_no + 1):
            race_id = f"{row.start_date.year}{course_code}{meeting_no:02d}{day_no:02d}01"
            url = f"https://race.sp.netkeiba.com/?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
            response = client.get(url)
            found_date, found_course, result_rows = parse_meta_date_course(response.text)
            if found_date == expected_date and found_course == expected_course and result_rows > 0:
                return meeting_no, day_no, race_id
    return None, None, None


def main() -> None:
    path = Path(".workstate/jra-srb/prediction-v1-validation/netkeiba_meeting_calendar.2025q4.csv")
    rows = load_rows(path)
    with httpx.Client(headers=NETKEIBA_HEADERS, timeout=20.0, follow_redirects=True) as client:
        print("course,start_date,expected_start_day_no,discovered_meeting_no,discovered_day_no,sample_race_id")
        for row in rows:
            meeting_no, day_no, race_id = discover_meeting_no(client, row)
            print(
                f"{row.course},{row.start_date.isoformat()},{row.start_day_no},"
                f"{meeting_no or ''},{day_no or ''},{race_id or ''}"
            )


if __name__ == "__main__":
    main()
