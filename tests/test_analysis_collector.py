from datetime import UTC, date, datetime
import sqlite3

import pytest

from jra_srb.analysis_collector import AnalysisCollectionOptions, AnalysisCollector
from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.cli import collect_analysis
from jra_srb.models import (
    MeetingRace,
    MeetingSnapshot,
    NetkeibaRaceResult,
    OddsEntry,
    PayoutEntry,
    RaceCard,
    RaceOdds,
    RaceResult,
    NetkeibaResultEntry,
    ResultEntry,
    Runner,
)


class FakeAnalysisService:
    def __init__(self, fail_result: bool = False) -> None:
        self.fail_result = fail_result
        self.card_calls = 0
        self.odds_calls = 0
        self.result_calls = 0

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[MeetingRace(race_no=11, race_id=f"{target_date:%Y%m%d}0611", race_name="Chiba Stakes")],
            fetched_at=datetime.now(UTC),
            source="meeting",
        )

    async def get_meetings_for_date(self, target_date: date) -> list[MeetingSnapshot]:
        return [await self.get_meeting(target_date, "nakayama")]

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int) -> RaceCard:
        self.card_calls += 1
        return RaceCard(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name="Chiba Stakes",
            course=course,
            runners=[Runner(horse_no="1", horse_name="Dragon Wells", odds="12.4", popularity="5")],
            fetched_at=datetime.now(UTC),
            source="card",
        )

    async def get_race_odds_by_number(self, target_date: date, course: str, race_no: int, bet_type: str) -> RaceOdds:
        self.odds_calls += 1
        return RaceOdds(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            bet_type=bet_type,
            entries=[OddsEntry(bet_type=bet_type, combination=["1", "2"], odds="16.1", popularity="8")],
            fetched_at=datetime.now(UTC),
            source="odds",
        )

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
        self.result_calls += 1
        if self.fail_result:
            raise LookupError("payout block not found")
        return RaceResult(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name="Chiba Stakes",
            results=[ResultEntry(rank="1", horse_no="1", horse_name="Dragon Wells")],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="1,610", popularity="8")],
            fetched_at=datetime.now(UTC),
            source="result",
        )


class FakeNarAnalysisService:
    def __init__(self) -> None:
        self.meeting_calls = 0
        self.card_calls = 0
        self.odds_calls = 0
        self.result_calls = 0

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        self.meeting_calls += 1
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[MeetingRace(race_no=1, race_id="202645061501", race_name="Spark Cup")],
            fetched_at=datetime.now(UTC),
            source="nar-meeting",
        )

    async def get_race_card(self, race_id: str) -> RaceCard:
        self.card_calls += 1
        return RaceCard(
            race_id=race_id,
            race_name="Spark Cup",
            course="kawasaki",
            distance="1500",
            surface="dirt",
            runners=[Runner(horse_no="1", horse_name="Nar Runner", jockey="Nar Jockey")],
            fetched_at=datetime.now(UTC),
            source="nar-card",
        )

    async def get_race_odds(self, race_id: str, bet_type: str) -> RaceOdds:
        self.odds_calls += 1
        return RaceOdds(
            race_id=race_id,
            bet_type=bet_type,
            entries=[OddsEntry(bet_type=bet_type, combination=["1", "2"], odds="8.5", popularity="3")],
            fetched_at=datetime.now(UTC),
            source="nar-odds",
        )

    async def get_race_result(self, race_id: str) -> NetkeibaRaceResult:
        self.result_calls += 1
        return NetkeibaRaceResult(
            race_id=race_id,
            race_name="Spark Cup",
            course="kawasaki",
            race_no="1",
            results=[
                NetkeibaResultEntry(
                    rank="1",
                    horse_no="1",
                    horse_name="Nar Runner",
                    jockey="Nar Jockey",
                    finish_time="1:36.8",
                )
            ],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="860", popularity="3")],
            fetched_at=datetime.now(UTC),
            source="nar-result",
        )


@pytest.mark.asyncio
async def test_analysis_collector_collects_card_odds_and_result(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    collector = AnalysisCollector(service=FakeAnalysisService(), store=store)  # type: ignore[arg-type]

    run_id = await collector.collect(
        AnalysisCollectionOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["nakayama"],
            include_card=True,
            include_odds=True,
            include_results=True,
            bet_types=["wide"],
        )
    )

    assert run_id
    assert store.count_rows("collection_runs") == 1
    assert store.count_rows("races") == 1
    assert store.count_rows("runners") == 1
    assert store.count_rows("odds_entries") == 1
    assert store.count_rows("result_entries") == 1
    assert store.count_rows("payouts") == 1
    assert store.count_rows("collection_errors") == 0


@pytest.mark.asyncio
async def test_analysis_collector_stops_at_live_request_limit(tmp_path):
    db_path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(db_path)
    collector = AnalysisCollector(service=FakeAnalysisService(), store=store)  # type: ignore[arg-type]

    run_id = await collector.collect(
        AnalysisCollectionOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["nakayama"],
            include_card=True,
            include_odds=False,
            include_results=True,
            max_live_requests=1,
        )
    )

    with sqlite3.connect(db_path) as conn:
        status = conn.execute("select status from collection_runs where run_id = ?", (run_id,)).fetchone()[0]

    assert status == "partial"
    assert store.count_rows("races") == 1
    assert store.count_rows("runners") == 0
    assert store.count_rows("result_entries") == 0


@pytest.mark.asyncio
async def test_analysis_collector_skip_existing_avoids_re_fetching_saved_payloads(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    service = FakeAnalysisService()
    collector = AnalysisCollector(service=service, store=store)  # type: ignore[arg-type]
    options = AnalysisCollectionOptions(
        from_date=date(2026, 3, 22),
        to_date=date(2026, 3, 22),
        courses=["nakayama"],
        include_card=True,
        include_odds=True,
        include_results=True,
        bet_types=["wide"],
        skip_existing=True,
    )

    await collector.collect(options)
    await collector.collect(options)

    assert service.card_calls == 1
    assert service.odds_calls == 1
    assert service.result_calls == 1


@pytest.mark.asyncio
async def test_analysis_collector_records_result_failure_and_continues(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    collector = AnalysisCollector(service=FakeAnalysisService(fail_result=True), store=store)  # type: ignore[arg-type]

    await collector.collect(
        AnalysisCollectionOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["nakayama"],
            include_card=True,
            include_odds=True,
            include_results=True,
            bet_types=["wide"],
        )
    )

    assert store.count_rows("races") == 1
    assert store.count_rows("odds_entries") == 1
    assert store.count_rows("result_entries") == 0
    assert store.count_rows("collection_errors") == 1


@pytest.mark.asyncio
async def test_collect_analysis_cli_writes_sqlite(tmp_path):
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "courses": "中山",
            "from_date": date(2026, 3, 22),
            "to_date": date(2026, 3, 22),
            "include_card": True,
            "include_odds": True,
            "include_results": True,
            "bet_types": "wide",
            "odds_timing": "final_or_near_final",
            "retries": 0,
        },
    )()

    run_id = await collect_analysis(args, service=FakeAnalysisService())  # type: ignore[arg-type]
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    assert run_id
    assert store.count_rows("races") == 1
    assert store.count_rows("odds_entries") == 1


@pytest.mark.asyncio
async def test_analysis_collector_auto_discovers_meetings(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    collector = AnalysisCollector(service=FakeAnalysisService(), store=store)  # type: ignore[arg-type]

    await collector.collect(
        AnalysisCollectionOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["all"],
            include_card=False,
            include_odds=False,
            include_results=True,
        )
    )

    assert store.count_rows("races") == 1
    assert store.count_rows("result_entries") == 1
    assert store.count_rows("collection_errors") == 0


@pytest.mark.asyncio
async def test_analysis_collector_collects_nar_course_into_existing_analysis_tables(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    nar_service = FakeNarAnalysisService()
    collector = AnalysisCollector(
        service=FakeAnalysisService(),
        store=store,
        nar_service=nar_service,  # type: ignore[arg-type]
    )

    await collector.collect(
        AnalysisCollectionOptions(
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            courses=["kawasaki"],
            include_card=True,
            include_odds=True,
            include_results=True,
            bet_types=["wide"],
            skip_existing=True,
        )
    )

    assert nar_service.meeting_calls == 1
    assert nar_service.card_calls == 1
    assert nar_service.odds_calls == 1
    assert nar_service.result_calls == 1
    assert store.count_rows("races") == 1
    assert store.count_rows("runners") == 1
    assert store.count_rows("odds_entries") == 1
    assert store.count_rows("result_entries") == 1
    assert store.count_rows("payouts") == 1
    assert store.count_rows("collection_errors") == 0

    with sqlite3.connect(tmp_path / "analysis.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        race = conn.execute("select race_id, course from races").fetchone()
        result = conn.execute("select race_id, horse_name, finish_time from result_entries").fetchone()

    assert race["race_id"] == "202645061501"
    assert race["course"] == "kawasaki"
    assert result["horse_name"] == "Nar Runner"
    assert result["finish_time"] == "1:36.8"
