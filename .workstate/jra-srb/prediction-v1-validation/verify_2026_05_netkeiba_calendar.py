from __future__ import annotations

import re
import sys

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
    race_ids = [
        "202604010101",
        "202605020101",
        "202608030101",
        "202604010401",
        "202605020401",
        "202608030401",
    ]
    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for race_id in race_ids:
            response = client.get(
                "https://race.sp.netkeiba.com/"
                f"?pid=race_result&race_id={race_id}&rf=race_toggle_menu"
            )
            title = re.search(r"<title>(.*?)</title>", response.text, re.S)
            meta = re.search(
                r'<meta name="description" content="(.*?)"', response.text, re.S
            )
            rows = response.text.count("Result_Num")
            print(f"race_id={race_id} status={response.status_code} rows={rows}")
            print("title=", (title.group(1) if title else "").strip()[:160])
            print("meta=", (meta.group(1) if meta else "").strip()[:220])


if __name__ == "__main__":
    main()
