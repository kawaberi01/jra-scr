from datetime import UTC, date, datetime

import pytest

from jra_srb.cli import build_parser, collect_results
from jra_srb.models import MeetingRace, MeetingSnapshot, RaceResult


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
