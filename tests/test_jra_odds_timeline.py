from datetime import UTC, date, datetime

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.jra_odds_timeline import (
    JraOddsTimelineCollector,
    build_timeline_tasks,
    parse_start_datetime,
)
from jra_srb.models import MeetingRace, MeetingSnapshot, OddsEntry, RaceOdds


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


@pytest.mark.asyncio
async def test_timeline_collector_refresh_existing_controls_append(tmp_path) -> None:
    target_date = date.today()
    observed_at = datetime.now(UTC)
    race = MeetingRace(
        race_no=1,
        race_id=f"{target_date:%Y%m%d}1001",
        start_time="00:00",
    )
    meeting = MeetingSnapshot(
        date=target_date,
        course="kokura",
        races=[race],
        fetched_at=observed_at,
        source="fixture",
    )

    class FakeTimelineService:
        def __init__(self) -> None:
            self.odds_calls = 0

        async def get_meetings_for_date(self, requested_date):
            assert requested_date == target_date
            return [meeting]

        async def get_race_odds_by_number(
            self,
            requested_date,
            course,
            race_no,
            bet_type,
            refresh,
        ):
            assert (requested_date, course, race_no, bet_type, refresh) == (
                target_date,
                "kokura",
                1,
                "win",
                True,
            )
            self.odds_calls += 1
            return RaceOdds(
                race_id=race.race_id,
                bet_type="win",
                entries=[OddsEntry(combination=["1"], odds="3.0")],
                fetched_at=datetime.now(UTC),
                source="fixture-refresh",
            )

    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_race(
        target_date,
        "kokura",
        race,
        source=meeting.source,
        fetched_at=observed_at,
    )
    store.write_odds(
        RaceOdds(
            race_id=race.race_id,
            bet_type="win",
            entries=[OddsEntry(combination=["1"], odds="3.2")],
            fetched_at=observed_at,
            source="fixture",
        ),
        bet_type="win",
        odds_timing="t_minus_0m",
    )
    service = FakeTimelineService()
    collector = JraOddsTimelineCollector(service, store)  # type: ignore[arg-type]

    skipped = await collector.collect(
        target_date,
        {"kokura"},
        [0],
        ["win"],
        max_lateness_seconds=1_000_000_000,
    )
    refreshed = await collector.collect(
        target_date,
        {"kokura"},
        [0],
        ["win"],
        max_lateness_seconds=1_000_000_000,
        refresh_existing=True,
    )

    assert skipped.skipped_existing == 1
    assert skipped.live_requests == 0
    assert refreshed.saved == 1
    assert refreshed.live_requests == 1
    assert service.odds_calls == 1
    assert store.count_rows("odds_snapshots") == 2
