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


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    prefix = sys.argv[1]
    max_day_no = int(sys.argv[2]) if len(sys.argv) >= 3 else 12
    sleep_seconds = float(sys.argv[3]) if len(sys.argv) >= 4 else 0.2
    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for day_no in range(1, max_day_no + 1):
            race_id = f"{prefix}{day_no:02d}01"
            response = client.get(
                "https://race.sp.netkeiba.com/"
                f"?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
            )
            title_match = re.search(r"<title>(.*?)</title>", response.text, re.S)
            title = (title_match.group(1) if title_match else "").strip()
            print(f"{race_id} {title}")
            time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
