"""概要: JRA時点収集の予定生成・保存・日次起動時の判定を検証する。
作成日: 不明
入力: pytestの一時ディレクトリと疑似開催データ。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_odds_timeline.py
注意事項: 外部通信は行わない。一時SQLiteを使用する。
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.jra_odds_timeline import (
    JraOddsTimelineCollector,
    build_timeline_tasks,
    parse_start_datetime,
)
from jra_srb.models import (
    MeetingRace,
    MeetingSnapshot,
    OddsEntry,
    RaceCard,
    RaceOdds,
    Runner,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "course_count,limit,expected_saved,expected_requests,stopped",
    [(2, None, 264, 336, False), (3, None, 396, 504, False),
     (3, 504, 396, 504, False), (3, 432, 338, 432, True),
     (3, 0, 0, 0, True), (3, 1, 0, 1, True)],
)
async def test_daily_request_budget_covers_cards_and_all_odds(
    course_count, limit, expected_saved, expected_requests, stopped, capsys,
) -> None:
    """2・3場の全12R完了と、明示上限での部分終了・境界を外部通信なしで検証する。"""
    target_date = date(2020, 1, 1)
    meetings = [
        MeetingSnapshot(
            date=target_date, course=course, source="fixture",
            fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
            races=[MeetingRace(race_no=number, race_id=f"{index}{number:02d}", start_time="00:00")
                   for number in range(1, 13)],
        )
        for index, course in enumerate(["tokyo", "kyoto", "niigata"][:course_count])
    ]
    service = Mock()
    service.get_meetings_for_date = AsyncMock(return_value=meetings)
    service.get_race_card_by_number = AsyncMock(return_value=object())
    service.get_race_odds_by_number = AsyncMock(return_value=object())
    store = Mock()
    store.has_odds_snapshot.return_value = False
    summary = await JraOddsTimelineCollector(service, store).collect(
        target_date, set(), [30, 10, 2], ["win", "quinella", "wide", "trio"],
        bet_type_offsets={"win": [30, 10, 2], "quinella": [30, 10, 2],
                          "wide": [30, 10, 2], "trio": [10, 2]},
        max_live_requests=limit, min_interval_seconds=0,
        max_lateness_seconds=1_000_000_000,
    )
    assert summary.saved == expected_saved
    assert summary.live_requests == expected_requests
    assert summary.planned_requests == course_count * 12 * 14
    assert summary.request_limit == (limit if limit is not None else course_count * 12 * 14)
    assert summary.limit_reached is stopped
    assert summary.unprocessed_odds == (course_count * 12 * 11 - expected_saved if stopped else 0)
    assert summary.failed == 0
    assert service.get_race_card_by_number.await_count + service.get_race_odds_by_number.await_count == expected_requests
    assert store.write_odds.call_count == expected_saved
    if not stopped:
        for course in ["tokyo", "kyoto", "niigata"][:course_count]:
            assert any(call.args[1:3] == (course, 12)
                       for call in service.get_race_odds_by_number.call_args_list)
    assert ("reason=request_limit_reached" in capsys.readouterr().out) is stopped


@pytest.mark.asyncio
async def test_request_budget_counts_failed_card_attempt(capsys) -> None:
    """出馬表の通信失敗も上限を消費し、上限を超えてオッズを取得しない。"""
    target_date = date(2020, 1, 1)
    meeting = MeetingSnapshot(
        date=target_date, course="tokyo", source="fixture",
        fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
        races=[MeetingRace(race_no=1, race_id="fixture1", start_time="00:00")],
    )
    service = Mock()
    service.get_meetings_for_date = AsyncMock(return_value=[meeting])
    service.get_race_card_by_number = AsyncMock(side_effect=RuntimeError("fixture"))
    service.get_race_odds_by_number = AsyncMock()
    store = Mock()
    store.has_odds_snapshot.return_value = False
    summary = await JraOddsTimelineCollector(service, store).collect(
        target_date, set(), [0], ["win"], max_live_requests=1,
        min_interval_seconds=0, max_lateness_seconds=1_000_000_000,
    )
    assert summary.failed == summary.live_requests == summary.unprocessed_odds == 1
    assert summary.limit_reached
    service.get_race_odds_by_number.assert_not_awaited()
    assert "unprocessed_odds=1" in capsys.readouterr().out


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
            self.card_calls = 0

        async def get_meetings_for_date(self, requested_date):
            assert requested_date == target_date
            return [meeting]

        async def get_race_card_by_number(
            self,
            requested_date,
            course,
            race_no,
            refresh,
        ):
            assert (requested_date, course, race_no, refresh) == (
                target_date,
                "kokura",
                1,
                True,
            )
            self.card_calls += 1
            return RaceCard(
                race_id=race.race_id,
                runners=[Runner(horse_no="1", horse_name="Runner")],
                fetched_at=datetime.now(UTC),
                source="fixture-card-refresh",
                data_status={
                    "runner_set": "complete",
                    "source_kind": "pre_race_card",
                },
            )

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
    assert refreshed.live_requests == 2
    assert service.card_calls == 1
    assert service.odds_calls == 1
    assert store.count_rows("race_card_snapshots") == 1
    assert store.count_rows("odds_snapshots") == 2


@pytest.mark.asyncio
async def test_timeline_collector_limits_bet_types_by_offset(tmp_path) -> None:
    target_date = date.today()
    observed_at = datetime.now(UTC)
    race = MeetingRace(race_no=1, race_id=f"{target_date:%Y%m%d}1001", start_time="00:00")
    meeting = MeetingSnapshot(
        date=target_date,
        course="kokura",
        races=[race],
        fetched_at=observed_at,
        source="fixture",
    )

    class FakeTimelineService:
        def __init__(self) -> None:
            self.odds_calls: list[str] = []
            self.card_calls = 0

        async def get_meetings_for_date(self, requested_date):
            assert requested_date == target_date
            return [meeting]

        async def get_race_card_by_number(self, *_args, **_kwargs):
            self.card_calls += 1
            return RaceCard(
                race_id=race.race_id,
                runners=[Runner(horse_no="1", horse_name="Runner")],
                fetched_at=datetime.now(UTC),
                source="fixture-card",
            )

        async def get_race_odds_by_number(self, _date, _course, _race_no, bet_type, refresh):
            assert refresh is True
            self.odds_calls.append(bet_type)
            return RaceOdds(
                race_id=race.race_id,
                bet_type=bet_type,
                entries=[OddsEntry(combination=["1"], odds="3.0")],
                fetched_at=datetime.now(UTC),
                source="fixture-odds",
            )

    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    service = FakeTimelineService()
    collector = JraOddsTimelineCollector(service, store)  # type: ignore[arg-type]

    summary = await collector.collect(
        target_date,
        {"kokura"},
        [30, 10, 2],
        ["win", "quinella", "wide", "trio"],
        bet_type_offsets={
            "win": [30, 10, 2],
            "quinella": [30, 10, 2],
            "wide": [30, 10, 2],
            "trio": [10, 2],
        },
        max_lateness_seconds=1_000_000_000,
    )

    assert summary.saved == 11
    assert summary.live_requests == 14
    assert service.odds_calls.count("trio") == 2
    assert service.card_calls == 3
    assert store.count_rows("odds_snapshots") == 11


class DailyMeetingService:
    """日次起動時の開催判定を外部通信なしで再現する。"""

    def __init__(self, meetings=None, error=None) -> None:
        """返却する開催一覧または取得例外を保持する。"""
        self.meetings = meetings or []
        self.error = error
        self.requested_dates = []

    async def get_meetings_for_date(self, requested_date):
        """要求日を記録し、疑似開催一覧を返すか指定例外を送出する。"""
        self.requested_dates.append(requested_date)
        if self.error is not None:
            raise self.error
        return self.meetings


@pytest.mark.asyncio
async def test_daily_collector_schedules_monday_meeting(tmp_path, capsys) -> None:
    """祝日月曜の開催でも通常の時点を組み立てる。"""
    target_date = date(2026, 10, 12)
    meeting = MeetingSnapshot(
        date=target_date,
        course="tokyo",
        races=[MeetingRace(race_no=8, race_id="202610120508", start_time="13時45分")],
        fetched_at=datetime(2026, 10, 12, tzinfo=UTC),
        source="fixture",
    )
    service = DailyMeetingService([meeting])
    summary = await JraOddsTimelineCollector(
        service, AnalysisSQLiteStore(tmp_path / "analysis.sqlite"),
    ).collect(target_date, set(), [30, 10, 2], ["win"], dry_run=True)

    assert target_date.weekday() == 0
    assert service.requested_dates == [target_date]
    assert summary.scheduled == 3
    assert summary.live_requests == summary.saved == summary.failed == 0
    assert "2026-10-12T13:15:00+09:00 tokyo 8R" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_daily_collector_exits_normally_without_meetings(tmp_path, capsys, dry_run) -> None:
    """非開催日は待機・個別レース取得をせず正常なゼロ件を返す。"""
    target_date = date(2026, 10, 13)
    service = DailyMeetingService()
    summary = await JraOddsTimelineCollector(
        service, AnalysisSQLiteStore(tmp_path / "analysis.sqlite"),
    ).collect(target_date, set(), [30, 10, 2], ["win"], dry_run=dry_run)

    assert service.requested_dates == [target_date]
    assert summary.scheduled == summary.saved == summary.failed == summary.live_requests == 0
    assert "no_meetings date=2026-10-13" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_daily_collector_rejects_meeting_without_start_times(tmp_path) -> None:
    """開催があるのに発走時刻が欠けている状態を非開催扱いにしない。"""
    target_date = date(2026, 10, 12)
    meeting = MeetingSnapshot(
        date=target_date,
        course="tokyo",
        races=[MeetingRace(race_no=8, race_id="202610120508")],
        fetched_at=datetime(2026, 10, 12, tzinfo=UTC),
        source="fixture",
    )
    with pytest.raises(ValueError, match="no valid start times"):
        await JraOddsTimelineCollector(
            DailyMeetingService([meeting]), AnalysisSQLiteStore(tmp_path / "analysis.sqlite"),
        ).collect(target_date, set(), [30, 10, 2], ["win"], dry_run=True)


@pytest.mark.asyncio
async def test_daily_collector_propagates_meeting_fetch_failure(tmp_path, capsys) -> None:
    """開催一覧の通信失敗を正常な非開催と誤判定しない。"""
    with pytest.raises(RuntimeError, match="meeting fetch failed"):
        await JraOddsTimelineCollector(
            DailyMeetingService(error=RuntimeError("meeting fetch failed")),
            AnalysisSQLiteStore(tmp_path / "analysis.sqlite"),
        ).collect(date(2026, 10, 12), set(), [30, 10, 2], ["win"])
    assert "no_meetings" not in capsys.readouterr().out
