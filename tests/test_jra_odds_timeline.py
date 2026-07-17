from datetime import UTC, date, datetime

from jra_srb.jra_odds_timeline import build_timeline_tasks, parse_start_datetime
from jra_srb.models import MeetingRace, MeetingSnapshot


def test_parse_start_datetime_accepts_japanese_time() -> None:
    parsed = parse_start_datetime(date(2026, 7, 18), "15時45分")

    assert parsed is not None
    assert parsed.isoformat() == "2026-07-18T15:45:00+09:00"


def test_build_timeline_tasks_filters_courses_and_orders_offsets() -> None:
    observed = datetime(2026, 7, 18, tzinfo=UTC)
    meetings = [
        MeetingSnapshot(
            date=date(2026, 7, 18),
            course="kokura",
            races=[MeetingRace(race_no=10, race_id="202607181010", start_time="15:00")],
            fetched_at=observed,
            source="fixture",
        ),
        MeetingSnapshot(
            date=date(2026, 7, 18),
            course="fukushima",
            races=[MeetingRace(race_no=10, race_id="202607180310", start_time="15:10")],
            fetched_at=observed,
            source="fixture",
        ),
    ]

    tasks = build_timeline_tasks(date(2026, 7, 18), meetings, {"kokura"}, [30, 10, 2])

    assert [task.timing_label for task in tasks] == ["t_minus_30m", "t_minus_10m", "t_minus_2m"]
    assert [task.target_at.strftime("%H:%M") for task in tasks] == ["14:30", "14:50", "14:58"]
    assert all(task.course == "kokura" for task in tasks)
