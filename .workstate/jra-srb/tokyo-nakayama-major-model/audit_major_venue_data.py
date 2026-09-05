from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


TARGET_CODES = ("05", "06")
TARGET_NAMES = {"05": "tokyo", "06": "nakayama"}


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table})")}


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(scalar(conn, f"select count(*) from {table}") or 0)


def target_race_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select r.*,
               substr(r.race_id, 9, 2) as course_code,
               (select count(*) from runners ru where ru.race_id = r.race_id) as runner_count,
               exists(select 1 from race_results rr where rr.race_id = r.race_id) as has_result,
               exists(select 1 from result_entries re where re.race_id = r.race_id) as has_entries,
               exists(select 1 from payouts p where p.race_id = r.race_id) as has_payouts,
               exists(select 1 from odds_snapshots os where os.race_id = r.race_id) as has_odds,
               exists(
                   select 1 from netkeiba_race_results nr
                   where nr.jra_race_id = r.race_id and nr.race_laps_json not in ('', '[]', 'null')
               ) as has_laps
        from races r
        where r.source like 'https://www.jra.go.jp/%'
          and substr(r.race_id, 9, 2) in ('05', '06')
        order by r.race_date, r.race_id
        """
    ).fetchall()


def period_key(race_date: str) -> str:
    if race_date < "2025-01-05":
        return "pre_2025"
    if race_date <= "2025-09-30":
        return "known_train"
    if race_date <= "2025-12-31":
        return "known_validation"
    if race_date <= "2026-06-28":
        return "known_holdout"
    return "post_known_holdout"


def classification(row: sqlite3.Row) -> str:
    name = str(row["race_name"] or "")
    surface = str(row["surface"] or "")
    if "障害" in name or "障" in surface:
        return "obstacle"
    if "新馬" in name:
        return "newcomer"
    return "flat_general"


def coverage(rows: list[sqlite3.Row]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, selected in {
        "all": rows,
        "known_train": [r for r in rows if period_key(r["race_date"]) == "known_train"],
        "known_validation": [r for r in rows if period_key(r["race_date"]) == "known_validation"],
        "known_holdout": [r for r in rows if period_key(r["race_date"]) == "known_holdout"],
        "post_known_holdout": [r for r in rows if period_key(r["race_date"]) == "post_known_holdout"],
    }.items():
        total = len(selected)
        result[label] = {
            "races": total,
            "date_min": min((r["race_date"] for r in selected), default=None),
            "date_max": max((r["race_date"] for r in selected), default=None),
            "with_runners": sum(int(r["runner_count"] or 0) > 0 for r in selected),
            "with_result": sum(bool(r["has_result"]) for r in selected),
            "with_result_entries": sum(bool(r["has_entries"]) for r in selected),
            "with_payouts": sum(bool(r["has_payouts"]) for r in selected),
            "with_any_odds_snapshot": sum(bool(r["has_odds"]) for r in selected),
            "with_laps": sum(bool(r["has_laps"]) for r in selected),
        }
    return result


def as_of_odds_audit(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select os.race_id, os.bet_type, os.odds_timing, os.fetched_at,
               r.race_date, r.start_time,
               substr(r.race_id, 9, 2) as course_code
        from odds_snapshots os join races r on r.race_id = os.race_id
        where r.source like 'https://www.jra.go.jp/%'
          and substr(r.race_id, 9, 2) in ('05', '06')
        """
    ).fetchall()
    timing = Counter(str(row["odds_timing"] or "missing") for row in rows)
    bet_types = Counter(str(row["bet_type"] or "missing") for row in rows)
    parsed = before_start = at_or_after_start = unparseable = 0
    for row in rows:
        start_time = str(row["start_time"] or "").strip()
        fetched_at = str(row["fetched_at"] or "").strip()
        try:
            start = datetime.fromisoformat(f"{row['race_date']}T{start_time}:00" if len(start_time) == 5 else f"{row['race_date']}T{start_time}")
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            if fetched.tzinfo is not None:
                fetched = fetched.replace(tzinfo=None)
            parsed += 1
            if fetched < start:
                before_start += 1
            else:
                at_or_after_start += 1
        except (TypeError, ValueError):
            unparseable += 1
    return {
        "snapshots": len(rows),
        "bet_types": dict(sorted(bet_types.items())),
        "odds_timing": dict(sorted(timing.items())),
        "timestamp_comparison": {
            "parsed": parsed,
            "before_start": before_start,
            "at_or_after_start": at_or_after_start,
            "unparseable": unparseable,
        },
    }


def audit(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = [str(row[0]) for row in conn.execute("select name from sqlite_master where type='table' order by name")]
        rows = target_race_rows(conn)
        by_course = Counter(TARGET_NAMES[str(row["course_code"])] for row in rows)
        by_month = Counter(str(row["race_date"])[:7] for row in rows)
        by_surface = Counter(str(row["surface"] or "missing") for row in rows)
        by_class = Counter(classification(row) for row in rows)
        by_distance = Counter(str(row["distance"] or "missing") for row in rows)
        by_race_no = Counter(str(row["race_no"] or "missing") for row in rows)
        by_field = Counter(
            "le_10" if int(row["runner_count"] or 0) <= 10 else "11_13" if int(row["runner_count"] or 0) <= 13 else "ge_14"
            for row in rows
        )
        payout_types = dict(
            conn.execute(
                """
                select p.bet_type, count(*)
                from payouts p join races r on r.race_id = p.race_id
                where r.source like 'https://www.jra.go.jp/%'
                  and substr(r.race_id, 9, 2) in ('05', '06')
                group by p.bet_type order by p.bet_type
                """
            ).fetchall()
        )
        duplicate_races = int(
            scalar(
                conn,
                "select count(*) from (select race_id from races group by race_id having count(*) > 1)",
            )
            or 0
        )
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "db_path": str(db_path),
            "db_size_bytes": db_path.stat().st_size,
            "tables": {table: table_count(conn, table) for table in tables},
            "schema_columns": {table: sorted(columns(conn, table)) for table in tables},
            "all_races": {
                "count": table_count(conn, "races"),
                "date_min": scalar(conn, "select min(race_date) from races"),
                "date_max": scalar(conn, "select max(race_date) from races"),
                "by_course": {
                    str(course): count
                    for course, count in conn.execute(
                        "select course, count(*) from races group by course order by course"
                    ).fetchall()
                },
                "samples_2025": [
                    dict(row)
                    for row in conn.execute(
                        "select race_id, race_date, course, race_name, source from races where race_date between '2025-01-01' and '2025-01-31' order by race_date, race_id limit 20"
                    ).fetchall()
                ],
            },
            "target_races": {
                "count": len(rows),
                "by_course": dict(sorted(by_course.items())),
                "by_month": dict(sorted(by_month.items())),
                "by_surface": dict(sorted(by_surface.items())),
                "by_class": dict(sorted(by_class.items())),
                "by_distance": dict(sorted(by_distance.items())),
                "by_race_no": dict(sorted(by_race_no.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 99)),
                "by_field_size": dict(sorted(by_field.items())),
                "duplicate_race_ids": duplicate_races,
                "coverage": coverage(rows),
                "payout_types": payout_types,
                "post_known_holdout_rows": [
                    {
                        "race_id": str(row["race_id"]),
                        "race_date": str(row["race_date"]),
                        "course": str(row["course"]),
                        "race_no": row["race_no"],
                        "race_name": row["race_name"],
                        "has_entries": bool(row["has_entries"]),
                        "has_payouts": bool(row["has_payouts"]),
                    }
                    for row in rows
                    if period_key(str(row["race_date"])) == "post_known_holdout"
                ],
            },
            "as_of_odds": as_of_odds_audit(conn),
        }
    finally:
        conn.close()


def markdown(report: dict[str, Any]) -> str:
    target = report["target_races"]
    lines = [
        "# 東京・中山主要場モデル データ監査",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- db: `{report['db_path']}`",
        f"- 全JRA race: {report['all_races']['count']} ({report['all_races']['date_min']}..{report['all_races']['date_max']})",
        f"- 東京・中山 race: {target['count']} / {target['by_course']}",
        "",
        "## 期間別coverage",
        "",
        "| period | races | date | result | entries | payout | odds | laps |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, item in target["coverage"].items():
        lines.append(
            f"| {name} | {item['races']} | {item['date_min']}..{item['date_max']} | "
            f"{item['with_result']} | {item['with_result_entries']} | {item['with_payouts']} | "
            f"{item['with_any_odds_snapshot']} | {item['with_laps']} |"
        )
    lines.extend(
        [
            "",
            "## セグメント",
            "",
            f"- surface: `{target['by_surface']}`",
            f"- class split: `{target['by_class']}`",
            f"- field size: `{target['by_field_size']}`",
            f"- payout types: `{target['payout_types']}`",
            f"- post-known rows: `{target['post_known_holdout_rows']}`",
            "",
            "## as-of odds",
            "",
            f"- bet types: `{report['as_of_odds']['bet_types']}`",
            f"- timing labels: `{report['as_of_odds']['odds_timing']}`",
            f"- timestamp comparison: `{report['as_of_odds']['timestamp_comparison']}`",
            "",
            "## 監査上の扱い",
            "",
            "- `at_or_after_start` のsnapshotは購入判断に使用しない。",
            "- 実取得oddsがない券種は候補を生成しない。",
            "- 新馬・障害は一般平地集計から分離する。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "artifacts")
    args = parser.parse_args()
    report = audit(args.db)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "data_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.output_dir / "data_audit.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    print(json.dumps({"all_races": {key: value for key, value in report["all_races"].items() if key != "by_course"}, "target_coverage": report["target_races"]["coverage"], "as_of_odds": report["as_of_odds"]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
