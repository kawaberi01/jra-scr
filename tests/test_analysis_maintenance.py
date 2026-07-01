from datetime import UTC, date, datetime

import pytest

from jra_srb.analysis_maintenance import (
    AnalysisJoinVerifier,
    AnalysisRunnerBackfiller,
    RunnerBackfillOptions,
)
from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.cli import main
from jra_srb.models import MeetingRace, PayoutEntry, RaceCard, RaceResult, ResultEntry, Runner


class FakeRunnerBackfillService:
    def __init__(self, fail_race_no: int | None = None) -> None:
        self.fail_race_no = fail_race_no
        self.calls: list[tuple[date, str, int]] = []

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int) -> RaceCard:
        self.calls.append((target_date, course, race_no))
        if race_no == self.fail_race_no:
            raise LookupError("card not found")
        return RaceCard(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name=f"Race {race_no}",
            course=course,
            runners=[
                Runner(
                    horse_no="1",
                    horse_name=f"Horse {race_no}",
                    jockey="Jockey",
                    trainer="Trainer",
                    sex_age="F3",
                    weight_carried="57.0",
                )
            ],
            fetched_at=datetime.now(UTC),
            source="fake-card",
        )


def _seed_race(store: AnalysisSQLiteStore, race_no: int) -> None:
    store.write_race(
        date(2026, 3, 22),
        "nakayama",
        MeetingRace(race_no=race_no, race_id=f"2026032206{race_no:02d}", race_name=f"Race {race_no}"),
        source="meeting",
        fetched_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_runner_backfill_only_missing_writes_runners(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    _seed_race(store, 2)
    store.write_card(
        date(2026, 3, 22),
        "nakayama",
        1,
        RaceCard(
            race_id="202603220601",
            race_name="Race 1",
            course="nakayama",
            runners=[Runner(horse_no="1", horse_name="Existing")],
            fetched_at=datetime.now(UTC),
            source="seed-card",
        ),
    )
    service = FakeRunnerBackfillService()

    summary = await AnalysisRunnerBackfiller(service=service, store=store).backfill(
        RunnerBackfillOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["nakayama"],
            only_missing=True,
        )
    )

    assert summary.target_count == 1
    assert summary.written_count == 1
    assert service.calls == [(date(2026, 3, 22), "nakayama", 2)]
    assert store.count_rows("runners") == 2
    assert store.count_rows("collection_errors") == 0


@pytest.mark.asyncio
async def test_runner_backfill_dry_run_reports_targets_without_fetching_or_writing(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    service = FakeRunnerBackfillService()

    summary = await AnalysisRunnerBackfiller(service=service, store=store).backfill(
        RunnerBackfillOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["nakayama"],
            only_missing=True,
            dry_run=True,
        )
    )

    assert summary.target_count == 1
    assert summary.processed_count == 0
    assert summary.skipped_count == 1
    assert summary.status == "dry-run"
    assert summary.run_id == "dry-run"
    assert service.calls == []
    assert store.count_rows("runners") == 0
    assert store.count_rows("collection_runs") == 0


@pytest.mark.asyncio
async def test_runner_backfill_records_race_error_and_continues(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    _seed_race(store, 2)
    service = FakeRunnerBackfillService(fail_race_no=1)

    summary = await AnalysisRunnerBackfiller(service=service, store=store).backfill(
        RunnerBackfillOptions(
            from_date=date(2026, 3, 22),
            to_date=date(2026, 3, 22),
            courses=["nakayama"],
            only_missing=True,
        )
    )

    assert summary.status == "failed"
    assert summary.failed_count == 1
    assert summary.written_count == 1
    assert store.count_rows("runners") == 1
    assert store.count_rows("collection_errors") == 1


@pytest.mark.asyncio
async def test_runner_backfill_is_idempotent_on_rerun(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    service = FakeRunnerBackfillService()
    backfiller = AnalysisRunnerBackfiller(service=service, store=store)
    options = RunnerBackfillOptions(
        from_date=date(2026, 3, 22),
        to_date=date(2026, 3, 22),
        courses=["nakayama"],
        only_missing=False,
    )

    await backfiller.backfill(options)
    await backfiller.backfill(options)

    assert store.count_rows("runners") == 1
    assert store.count_rows("collection_runs") == 2


def test_verify_analysis_joins_succeeds_when_card_and_result_join(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    store.write_card(
        date(2026, 3, 22),
        "nakayama",
        1,
        RaceCard(
            race_id="202603220601",
            race_name="Race 1",
            course="nakayama",
            runners=[Runner(horse_no="1", horse_name="Horse 1", jockey="Jockey")],
            fetched_at=datetime.now(UTC),
            source="card",
        ),
    )
    store.write_result(
        RaceResult(
            race_id="202603220601",
            race_name="Race 1",
            results=[ResultEntry(rank="1", horse_no="1", horse_name="Horse 1")],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="100")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    result = AnalysisJoinVerifier(store).verify(date(2026, 3, 22), date(2026, 3, 22), sample_size=3)

    assert result.ok is True
    assert result.result_runner_join_rows == 1
    assert result.payout_runner_race_join_rows == 1
    assert result.samples[0].race_id == "202603220601"


def test_verify_analysis_joins_fails_when_runners_are_missing(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    store.write_result(
        RaceResult(
            race_id="202603220601",
            race_name="Race 1",
            results=[ResultEntry(rank="1", horse_no="1", horse_name="Horse 1")],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="100")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    result = AnalysisJoinVerifier(store).verify(date(2026, 3, 22), date(2026, 3, 22), sample_size=3)

    assert result.ok is False
    assert result.missing_runner_races == 1
    assert result.result_runner_join_rows == 0


def test_verify_analysis_joins_cli_returns_zero_when_joined(tmp_path, capsys):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    store.write_card(
        date(2026, 3, 22),
        "nakayama",
        1,
        RaceCard(
            race_id="202603220601",
            race_name="Race 1",
            course="nakayama",
            runners=[Runner(horse_no="1", horse_name="Horse 1", jockey="Jockey")],
            fetched_at=datetime.now(UTC),
            source="card",
        ),
    )
    store.write_result(
        RaceResult(
            race_id="202603220601",
            race_name="Race 1",
            results=[ResultEntry(rank="1", horse_no="1", horse_name="Horse 1")],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="100")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    exit_code = main(
        [
            "verify-analysis-joins",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--sample-size",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "result_runner_join_rows=1" in output
    assert "sample=202603220601|1|Horse 1|Jockey" in output


def test_verify_analysis_joins_cli_returns_nonzero_when_runners_are_missing(tmp_path, capsys):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    _seed_race(store, 1)
    store.write_result(
        RaceResult(
            race_id="202603220601",
            race_name="Race 1",
            results=[ResultEntry(rank="1", horse_no="1", horse_name="Horse 1")],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="100")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    exit_code = main(
        [
            "verify-analysis-joins",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--sample-size",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "missing_runner_races=1" in output
