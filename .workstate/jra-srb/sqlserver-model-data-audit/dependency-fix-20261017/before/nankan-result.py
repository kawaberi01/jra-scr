from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


DEFAULT_DB = Path(r"D:\develop\jra-scr\data\db\analysis.sqlite")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch one Nankan race result from local API and save it into analysis.sqlite."
    )
    parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD.")
    parser.add_argument("--course", required=True, help="kawasaki / urawa / funabashi / ohi")
    parser.add_argument("--race", dest="race_no", type=int, required=True, help="Race number.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to analysis.sqlite")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    return parser.parse_args()


def fetch_result(base_url: str, date_: str, course: str, race_no: int) -> dict:
    url = f"{base_url.rstrip('/')}/nankan/meetings/{date_}/{course}/races/{race_no}/result"
    try:
        with urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SystemExit(f"HTTP error while fetching result: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise SystemExit(f"Failed to reach local API: {exc.reason}") from exc


def parse_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value).replace(",", ""))
    return None if match is None else int(match.group(0))


def save_result(db_path: Path, result: dict) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            insert into race_results (race_id, race_name, fetched_at, source)
            values (?, ?, ?, ?)
            on conflict(race_id) do update set
                race_name = excluded.race_name,
                fetched_at = excluded.fetched_at,
                source = excluded.source
            """,
            (
                result["race_id"],
                result.get("race_name"),
                result.get("fetched_at"),
                result.get("source"),
            ),
        )

        cur.execute("delete from result_entries where race_id = ?", (result["race_id"],))
        for entry in result.get("results", []):
            cur.execute(
                """
                insert into result_entries
                (race_id, rank, horse_no, horse_name, jockey, finish_time)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    result["race_id"],
                    parse_int(entry.get("rank")),
                    entry.get("horse_no"),
                    entry.get("horse_name"),
                    entry.get("jockey"),
                    entry.get("time"),
                ),
            )

        cur.execute("delete from payouts where race_id = ?", (result["race_id"],))
        for payout in result.get("payouts", []):
            cur.execute(
                """
                insert into payouts (race_id, bet_type, combination, payout, popularity)
                values (?, ?, ?, ?, ?)
                """,
                (
                    result["race_id"],
                    payout.get("bet_type"),
                    payout.get("combination"),
                    parse_int(payout.get("payout")),
                    parse_int(payout.get("popularity")),
                ),
            )

        conn.commit()

        counts = {
            "race_results": cur.execute(
                "select count(*) from race_results where race_id = ?",
                (result["race_id"],),
            ).fetchone()[0],
            "result_entries": cur.execute(
                "select count(*) from result_entries where race_id = ?",
                (result["race_id"],),
            ).fetchone()[0],
            "payouts": cur.execute(
                "select count(*) from payouts where race_id = ?",
                (result["race_id"],),
            ).fetchone()[0],
        }
        return counts
    finally:
        conn.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = fetch_result(args.base_url, args.date, args.course, args.race_no)
    counts = save_result(args.db, result)
    print(
        json.dumps(
            {
                "race_id": result["race_id"],
                "race_name": result.get("race_name"),
                "db": str(args.db),
                "counts": counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
