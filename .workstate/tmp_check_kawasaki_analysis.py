import sqlite3
import asyncio

from jra_srb.nar_netkeiba_service import NarNetkeibaService


def safe_join(row) -> str:
    values = []
    for value in row:
        if value is None:
            values.append("")
            continue
        if isinstance(value, str):
            values.append(value.encode("unicode_escape").decode())
            continue
        values.append(str(value))
    return "|".join(values)


def main() -> None:
    conn = sqlite3.connect(r"data/analysis.sqlite")
    queries = {
        "races": "select count(1) from races where race_date='2026-07-06' and course='kawasaki'",
        "runners": "select count(1) from runners where race_id in (select race_id from races where race_date='2026-07-06' and course='kawasaki')",
        "race_results": "select count(1) from race_results where race_id in (select race_id from races where race_date='2026-07-06' and course='kawasaki')",
        "result_entries": "select count(1) from result_entries where race_id in (select race_id from races where race_date='2026-07-06' and course='kawasaki')",
        "payouts": "select count(1) from payouts where race_id in (select race_id from races where race_date='2026-07-06' and course='kawasaki')",
    }
    for key, sql in queries.items():
        print(f"{key}={conn.execute(sql).fetchone()[0]}")

    print("-- races --")
    for row in conn.execute(
        """
        select race_id, race_no, race_name, meeting_no, meeting_day
        from races
        where race_date='2026-07-06' and course='kawasaki'
        order by race_no
        """
    ):
        print(safe_join(row))

    print("-- runs --")
    for row in conn.execute(
        """
        select status, run_id, created_at, finished_at
        from collection_runs
        order by created_at desc
        limit 3
        """
    ):
        print(safe_join(row))

    print("-- errors --")
    for row in conn.execute(
        """
        select race_id, course, race_no, stage, error_type, substr(error_message, 1, 120)
        from collection_errors
        where race_date='2026-07-06' and course='kawasaki'
        order by created_at desc
        limit 10
        """
    ):
        print(safe_join(row))

    print("-- live nar service --")
    asyncio.run(check_nar_service())


async def check_nar_service() -> None:
    service = NarNetkeibaService()
    calendar = await service.get_calendar(2026, 7, "kawasaki")
    print(f"calendar_entries={len(calendar.entries)}")
    if calendar.entries:
        first = calendar.entries[0]
        print(f"calendar_first={first.date.isoformat()}|{first.course_key}|{first.kaisai_id}")
    meeting = await service.get_meeting(__import__("datetime").date(2026, 7, 6), "kawasaki")
    print(f"meeting_course={meeting.course.encode('unicode_escape').decode()}")
    print(f"meeting_races={len(meeting.races)}")
    if meeting.races:
        sample = meeting.races[0]
        race_name = "" if sample.race_name is None else sample.race_name.encode("unicode_escape").decode()
        print(f"meeting_first_race={sample.race_no}|{sample.race_id}|{race_name}")


if __name__ == "__main__":
    main()
