"""2024年JRA netkeiba結果を、月単位で順番に補完する運用ランナー。"""

from __future__ import annotations

import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "data" / "db" / "analysis.sqlite"
CALENDAR = Path(__file__).with_name("netkeiba_meeting_calendar.2024_h1.csv")
OUTPUT_DIR = Path(__file__).parent
MONTHS = [
    ("2024-02", "2024-02-01", "2024-02-29"),
    ("2024-03", "2024-03-01", "2024-03-31"),
    ("2024-04", "2024-04-01", "2024-04-30"),
    ("2024-05", "2024-05-01", "2024-05-31"),
    ("2024-06", "2024-06-01", "2024-06-30"),
]


def log(message: str) -> None:
    print(f"{datetime.now().astimezone().isoformat()} {message}", flush=True)


def scalar(sql: str, params: tuple[str, str]) -> int:
    with sqlite3.connect(DB_PATH) as connection:
        return int(connection.execute(sql, params).fetchone()[0])


def race_count(start: str, end: str) -> int:
    return scalar(
        "SELECT COUNT(*) FROM races WHERE race_date BETWEEN ? AND ?",
        (start, end),
    )


def netkeiba_count(start: str, end: str) -> int:
    return scalar(
        """
        SELECT COUNT(*)
        FROM netkeiba_race_results n
        JOIN races r ON r.race_id = n.jra_race_id
        WHERE r.race_date BETWEEN ? AND ?
        """,
        (start, end),
    )


def run(command: list[str]) -> None:
    log("exec=" + subprocess.list2cmdline(command))
    subprocess.run(command, cwd=ROOT, check=True)


def wait_for_january() -> None:
    start, end = "2024-01-16", "2024-01-31"
    expected = race_count(start, end)
    for _ in range(480):
        saved = netkeiba_count(start, end)
        log(f"january_wait expected={expected} saved={saved}")
        if saved == expected:
            return
        time.sleep(30)
    raise TimeoutError("2024-01-16..31 netkeiba collection did not complete")


def process_month(label: str, start: str, end: str) -> None:
    expected = race_count(start, end)
    if expected == 0:
        raise RuntimeError(f"{label}: no races found")

    mapping_path = OUTPUT_DIR / f"netkeiba_mapping.{label}.csv"
    run(
        [
            "rtk",
            "uv",
            "run",
            "jra-srb",
            "generate-netkeiba-mapping",
            "--from-date",
            start,
            "--to-date",
            end,
            "--db",
            str(DB_PATH.relative_to(ROOT)),
            "--meeting-calendar-csv",
            str(CALENDAR.relative_to(ROOT)),
            "--output",
            str(mapping_path.relative_to(ROOT)),
            "--save-to-db",
        ]
    )
    run(
        [
            "rtk",
            "uv",
            "run",
            "jra-srb",
            "collect-netkeiba-results",
            "--from-date",
            start,
            "--to-date",
            end,
            "--db",
            str(DB_PATH.relative_to(ROOT)),
            "--use-db-mapping",
            "--max-live-requests",
            str(expected),
            "--min-interval-seconds",
            "3",
            "--retries",
            "1",
        ]
    )
    saved = netkeiba_count(start, end)
    if saved != expected:
        raise RuntimeError(
            f"{label}: netkeiba coverage incomplete expected={expected} saved={saved}"
        )
    run(
        [
            "rtk",
            "uv",
            "run",
            "jra-srb",
            "verify-analysis-joins",
            "--from-date",
            start,
            "--to-date",
            end,
            "--db",
            str(DB_PATH.relative_to(ROOT)),
        ]
    )
    log(f"{label}: complete races={expected} netkeiba={saved}")


def main() -> int:
    wait_for_january()
    for month in MONTHS:
        process_month(*month)
    log("2024_h1_sequential_backfill: complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"FAILED: {error}")
        raise
