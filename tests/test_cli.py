from datetime import UTC, date, datetime

import pytest

from jra_srb.cli import collect_results
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
