from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
RACES_JSON = WORKSTATE_DIR / "v1_validation_races.json"
DB_PATH = Path("data/analysis.sqlite")


def load_evaluations() -> list[dict]:
    with RACES_JSON.open(encoding="utf-8") as stream:
        return json.load(stream)


def print_reason_summary(rows: list[dict]) -> None:
    reasons = Counter()
    by_course: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row["status"] != "excluded":
            continue
        reason = row.get("reason") or "unknown"
        reasons[reason] += 1
        by_course[row["course_code"]][reason] += 1

    print("TOP_REASONS")
    for reason, count in reasons.most_common(15):
        print(reason, count)

    print()
    print("COURSE_EXCLUSIONS")
    for course_code, counts in sorted(by_course.items()):
        print(course_code, sum(counts.values()), counts.most_common(8))


def print_sample_db_state(rows: list[dict], reason: str, limit: int = 6) -> None:
    selected = [row for row in rows if row.get("reason") == reason][:limit]
    if not selected:
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        print()
        print("SAMPLES", reason)
        for row in selected:
            netkeiba_race_id = row["netkeiba_race_id"]
            parent = conn.execute(
                """
                select netkeiba_race_id, jra_race_id, race_date, course, race_no, race_name, source
                from netkeiba_race_results
                where netkeiba_race_id = ?
                """,
                (netkeiba_race_id,),
            ).fetchone()
            entry_count = conn.execute(
                "select count(1) from netkeiba_result_entries where netkeiba_race_id = ?",
                (netkeiba_race_id,),
            ).fetchone()[0]
            payout_count = conn.execute(
                "select count(1) from netkeiba_payouts where netkeiba_race_id = ?",
                (netkeiba_race_id,),
            ).fetchone()[0]
            print(
                row["jra_race_id"],
                row["course_code"],
                row["race_no"],
                netkeiba_race_id,
                dict(parent) if parent else None,
                "entries",
                entry_count,
                "payouts",
                payout_count,
            )
    finally:
        conn.close()


def print_name_mismatch_samples(rows: list[dict], limit: int = 3) -> None:
    selected = [row for row in rows if str(row.get("reason", "")).startswith("low_name_match:")][:limit]
    if not selected:
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        print()
        print("LOW_NAME_MATCH_SAMPLES")
        for row in selected:
            jra_race_id = row["jra_race_id"]
            netkeiba_race_id = row["netkeiba_race_id"]
            jra_names = [
                item[0]
                for item in conn.execute(
                    """
                    select horse_name
                    from runners
                    where race_id = ?
                    order by cast(horse_no as integer), horse_no
                    """,
                    (jra_race_id,),
                ).fetchall()
            ]
            nk_names = [
                item[0]
                for item in conn.execute(
                    """
                    select horse_name
                    from netkeiba_result_entries
                    where netkeiba_race_id = ?
                    order by rank, horse_no
                    """,
                    (netkeiba_race_id,),
                ).fetchall()
            ]
            exact_matches = len(set(jra_names) & set(nk_names))
            print(jra_race_id, netkeiba_race_id, row["reason"], "exact_matches", exact_matches)
            print("  JRA:", ascii(jra_names[:6]))
            print("  NK :", ascii(nk_names[:6]))
    finally:
        conn.close()


def main() -> None:
    rows = load_evaluations()
    print_reason_summary(rows)
    print_sample_db_state(rows, "missing_result_or_payout")
    print_name_mismatch_samples(rows)


if __name__ == "__main__":
    main()
