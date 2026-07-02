from datetime import UTC, date, datetime

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.cli import build_parser, collect_netkeiba_results, collect_results, generate_netkeiba_mapping
from jra_srb.models import MeetingRace, MeetingSnapshot, NetkeibaRaceResult, RaceResult


class FakeCliService:
    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[MeetingRace(race_no=1, race_id=f"{target_date:%Y%m%d}0601")],
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_meetings_for_date(self, target_date: date) -> list[MeetingSnapshot]:
        return [await self.get_meeting(target_date, "nakayama")]

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
        return RaceResult(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            fetched_at=datetime.now(UTC),
            source="fake",
        )


class FakeNetkeibaCliService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_race_result(self, race_id: str) -> NetkeibaRaceResult:
        self.calls.append(race_id)
        return NetkeibaRaceResult(
            race_id=race_id,
            race_name="Netkeiba Sample",
            date="2026-05-02",
            course="Tokyo",
            race_no="11",
            fetched_at=datetime.now(UTC),
            source="fake-netkeiba",
        )


@pytest.mark.asyncio
async def test_collect_results_cli_uses_normalized_course_and_writes_jsonl(tmp_path):
    args = type(
        "Args",
        (),
        {
            "storage": "jsonl",
            "output": tmp_path / "results.jsonl",
            "courses": "中山",
            "from_date": date(2026, 3, 22),
            "to_date": date(2026, 3, 22),
            "retries": 0,
        },
    )()

    await collect_results(args, service=FakeCliService())  # type: ignore[arg-type]

    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_collect_results_cli_accepts_all_for_auto_discovery(tmp_path):
    args = type(
        "Args",
        (),
        {
            "storage": "jsonl",
            "output": tmp_path / "results.jsonl",
            "courses": "all",
            "from_date": date(2026, 3, 22),
            "to_date": date(2026, 3, 22),
            "retries": 0,
        },
    )()

    await collect_results(args, service=FakeCliService())  # type: ignore[arg-type]

    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8")


def test_cli_parser_accepts_analysis_maintenance_commands(tmp_path):
    parser = build_parser()

    backfill = parser.parse_args(
        [
            "backfill-analysis-runners",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--courses",
            "all",
            "--only-missing",
            "--retries",
            "1",
            "--min-interval-seconds",
            "0.1",
            "--limit",
            "5",
            "--dry-run",
        ]
    )
    verify = parser.parse_args(
        [
            "verify-analysis-joins",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--sample-size",
            "3",
        ]
    )

    assert backfill.command == "backfill-analysis-runners"
    assert backfill.only_missing is True
    assert verify.command == "verify-analysis-joins"
    assert verify.sample_size == 3


def test_cli_parser_accepts_collect_netkeiba_results(tmp_path):
    parser = build_parser()

    args = parser.parse_args(
        [
            "collect-netkeiba-results",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--mapping-csv",
            str(tmp_path / "mapping.csv"),
            "--from-date",
            "2026-05-01",
            "--to-date",
            "2026-05-31",
            "--max-live-requests",
            "3",
            "--min-interval-seconds",
            "0",
            "--refresh",
            "--dry-run",
            "--limit",
            "2",
        ]
    )

    assert args.command == "collect-netkeiba-results"
    assert args.max_live_requests == 3
    assert args.refresh is True
    assert args.dry_run is True
    assert args.limit == 2


@pytest.mark.asyncio
async def test_collect_netkeiba_results_writes_and_skips_saved_results(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no",
                "202606280301,202605021211,2026-05-02,tokyo,11",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": False,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    first = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]
    second = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert first.collected_count == 1
    assert first.skipped_count == 0
    assert second.collected_count == 0
    assert second.skipped_count == 1
    assert service.calls == ["202605021211"]


@pytest.mark.asyncio
async def test_collect_netkeiba_results_stops_at_live_request_limit(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no",
                "202606280301,202605021211,2026-05-02,tokyo,11",
                "202606280302,202605021212,2026-05-02,tokyo,12",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 1,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": False,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    summary = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert summary.collected_count == 1
    assert summary.live_request_limit_reached is True
    assert service.calls == ["202605021211"]


@pytest.mark.asyncio
async def test_collect_netkeiba_results_dry_run_does_not_call_live_service_and_reports_counts(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no,mapping_status,mapping_note",
                "202606280301,202605021211,2026-05-02,tokyo,11,mapped,ok",
                "202606280302,,2026-05-02,tokyo,12,unmapped,no calendar",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": True,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    summary = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert summary.dry_run is True
    assert summary.target_count == 2
    assert summary.saved_count == 0
    assert summary.unsaved_count == 1
    assert summary.planned_request_count == 1
    assert summary.unmappable_count == 1
    assert service.calls == []


@pytest.mark.asyncio
async def test_collect_netkeiba_results_limit_restricts_targets_before_collection(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no",
                "202606280301,202605021211,2026-05-02,tokyo,11",
                "202606280302,202605021212,2026-05-02,tokyo,12",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": False,
            "limit": 1,
        },
    )()
    service = FakeNetkeibaCliService()

    summary = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert summary.target_count == 1
    assert summary.collected_count == 1
    assert service.calls == ["202605021211"]


def test_generate_netkeiba_mapping_restores_course_from_jra_race_id_and_writes_unmapped_rows(tmp_path):
    db = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(db)
    store.write_race(
        date(2026, 5, 2),
        "course: 1,600m dirt left",
        MeetingRace(race_no=11, race_id="202605020511", race_name="Mapped"),
    )
    with store._connect() as conn:
        conn.execute(
            """
            insert into races (race_id, race_date, course, race_no, race_name)
            values (?, ?, ?, ?, ?)
            """,
            ("bad-race-id", "2026-05-02", "tokyo", 12, "Unmapped"),
        )
    output = tmp_path / "mapping.csv"
    args = type(
        "Args",
        (),
        {
            "db": db,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "output": output,
            "meeting_calendar_csv": None,
            "limit": None,
        },
    )()

    summary = generate_netkeiba_mapping(args)
    lines = output.read_text(encoding="utf-8").splitlines()

    assert summary.total_count == 2
    assert summary.mapped_count == 1
    assert summary.unmapped_count == 1
    assert lines[0] == "jra_race_id,netkeiba_race_id,race_date,course,race_no,mapping_status,mapping_note"
    assert "mapped_estimated" in lines[1]
    assert ",tokyo," in lines[1]
    assert "unmapped" in lines[2]
    assert "invalid jra_race_id=bad-race-id" in lines[2]


def test_generate_netkeiba_mapping_uses_calendar_context_before_from_date(tmp_path):
    db = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(db)
    store.write_race(
        date(2025, 10, 4),
        "tokyo",
        MeetingRace(race_no=1, race_id="202510040501", race_name="Context"),
    )
    store.write_race(
        date(2025, 10, 5),
        "tokyo",
        MeetingRace(race_no=11, race_id="202510050511", race_name="Target"),
    )
    calendar = tmp_path / "calendar.csv"
    calendar.write_text(
        "\n".join(
            [
                "course,meeting_no,start_date,start_day_no",
                "tokyo,4,2025-10-04,1",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "mapping.csv"
    args = type(
        "Args",
        (),
        {
            "db": db,
            "from_date": date(2025, 10, 5),
            "to_date": date(2025, 10, 5),
            "output": output,
            "meeting_calendar_csv": calendar,
            "limit": None,
        },
    )()

    summary = generate_netkeiba_mapping(args)
    lines = output.read_text(encoding="utf-8").splitlines()

    assert summary.total_count == 1
    assert "202505040211" in lines[1]
    assert "mapping_status,mapping_note" in lines[0]
