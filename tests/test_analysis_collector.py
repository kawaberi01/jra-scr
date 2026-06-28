from datetime import UTC, date, datetime

import pytest

from jra_srb.analysis_collector import AnalysisCollectionOptions, AnalysisCollector
from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.cli import collect_analysis
from jra_srb.models import (
    MeetingRace,
    MeetingSnapshot,
    OddsEntry,
    PayoutEntry,
    RaceCard,
    RaceOdds,
    RaceResult,
    ResultEntry,
    Runner,
)


class FakeAnalysisService:
    def __init__(self, fail_result: bool = False) -> None:
        self.fail_result = fail_result

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[MeetingRace(race_no=11, race_id=f"{target_date:%Y%m%d}0611", race_name="Chiba Stakes")],
            fetched_at=datetime.now(UTC),
            source="meeting",
        )

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int) -> RaceCard:
        return RaceCard(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name="Chiba Stakes",
            course=course,
            runners=[Runner(horse_no="1", horse_name="Dragon Wells", odds="12.4", popularity="5")],
            fetched_at=datetime.now(UTC),
            source="card",
        )

    async def get_race_odds_by_number(self, target_date: date, course: str, race_no: int, bet_type: str) -> RaceOdds:
        return RaceOdds(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            bet_type=bet_type,
            entries=[OddsEntry(bet_type=bet_type, combination=["1", "2"], odds="16.1", popularity="8")],
            fetched_at=datetime.now(UTC),
            source="odds",
        )

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
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
