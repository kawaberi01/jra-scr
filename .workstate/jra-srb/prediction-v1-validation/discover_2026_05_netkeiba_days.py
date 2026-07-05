from __future__ import annotations

import re
import sys
import time

import httpx


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

COURSES = {
    "niigata": ("04", 1),
    "tokyo": ("05", 2),
    "kyoto": ("08", 3),
}


def title_date(title: str) -> str | None:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for course, (course_code, meeting_no) in COURSES.items():
            print(f"[{course}]")
            for day_no in range(1, 13):
                race_id = f"2026{course_code}{meeting_no:02d}{day_no:02d}01"
                response = client.get(
                    "https://race.sp.netkeiba.com/"
                    f"?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
                )
                title = re.search(r"<title>(.*?)</title>", response.text, re.S)
                title_text = (title.group(1) if title else "").strip()
                print(
                    f"{day_no:02d} {race_id} {title_date(title_text) or '-'} "
                    f"rows={response.text.count('Result_Num')} title={title_text[:60]}"
                )
                time.sleep(1.0)


if __name__ == "__main__":
    main()
