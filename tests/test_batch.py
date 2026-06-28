from datetime import UTC, date, datetime
import json

import pytest

from jra_srb.batch import JsonlRaceResultStorage, PastResultCollector, SQLiteRaceResultStorage
from jra_srb.models import MeetingRace, MeetingSnapshot, PayoutEntry, RaceResult, ResultEntry


class FakeService:
    def __init__(self) -> None:
        self.meeting_calls: list[tuple[date, str]] = []
        self.result_calls: list[tuple[date, str, int]] = []
        self.failures_before_success: dict[str, int] = {}

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        self.meeting_calls.append((target_date, course))
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[
                MeetingRace(race_no=1, race_id=f"{target_date:%Y%m%d}0601", race_name="1R"),
                MeetingRace(race_no=2, race_id=f"{target_date:%Y%m%d}0602", race_name="2R"),
            ],
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
        self.result_calls.append((target_date, course, race_no))
        key = f"{target_date.isoformat()}:{course}:{race_no}"
        remaining_failures = self.failures_before_success.get(key, 0)
        if remaining_failures > 0:
            self.failures_before_success[key] = remaining_failures - 1
            raise RuntimeError(f"temporary failure for {key}")
        return RaceResult(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name=f"{race_no}R",
            results=[
                ResultEntry(
                    rank="1",
                    horse_no=str(race_no),
                    horse_name=f"Horse {race_no}",
                    jockey="Jockey",
                    time="1:10.0",
                )
            ],
            payouts=[
                PayoutEntry(
                    bet_type="単勝",
                    combination=str(race_no),
                    payout="100",
                    popularity="1",
                )
            ],
            fetched_at=datetime.now(UTC),
            source="fake",
        )


@pytest.mark.asyncio
async def test_collect_results_range_calls_service_for_each_day():
    service = FakeService()
    collector = PastResultCollector(service=service)  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 22), ["nakayama", "hanshin"])

    assert service.meeting_calls == [
        (date(2026, 3, 21), "nakayama"),
        (date(2026, 3, 21), "hanshin"),
        (date(2026, 3, 22), "nakayama"),
        (date(2026, 3, 22), "hanshin"),
    ]


@pytest.mark.asyncio
async def test_collect_persists_each_race_result_as_jsonl(tmp_path):
    service = FakeService()
    storage = JsonlRaceResultStorage(tmp_path / "results.jsonl")
    collector = PastResultCollector(service=service, storage=storage)  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 21), ["nakayama"])

    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["race_id"] == "202603210601"
    assert first["date"] == "2026-03-21"
    assert first["course"] == "nakayama"
    assert first["race_no"] == 1
    assert first["result"]["results"][0]["horse_name"] == "Horse 1"
    assert first["result"]["payouts"][0]["bet_type"] == "単勝"


@pytest.mark.asyncio
async def test_collect_skips_already_persisted_race_ids(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(
        json.dumps(
            {
                "race_id": "202603210601",
                "date": "2026-03-21",
                "course": "nakayama",
                "race_no": 1,
                "result": {"race_id": "202603210601"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    service = FakeService()
    storage = JsonlRaceResultStorage(path)
    collector = PastResultCollector(service=service, storage=storage)  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 21), ["nakayama"])

    assert service.result_calls == [(date(2026, 3, 21), "nakayama", 2)]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.asyncio
async def test_collect_retries_temporary_result_fetch_failure(tmp_path):
    service = FakeService()
    service.failures_before_success["2026-03-21:nakayama:2"] = 1
    storage = JsonlRaceResultStorage(tmp_path / "results.jsonl")
    collector = PastResultCollector(
        service=service,
        storage=storage,
        retries=2,
    )  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 21), ["nakayama"])

    assert service.result_calls == [
        (date(2026, 3, 21), "nakayama", 1),
        (date(2026, 3, 21), "nakayama", 2),
        (date(2026, 3, 21), "nakayama", 2),
    ]
    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_jsonl_storage_reads_results_and_skips_broken_lines(tmp_path):
    service = FakeService()
    path = tmp_path / "results.jsonl"
    storage = JsonlRaceResultStorage(path)
    collector = PastResultCollector(service=service, storage=storage)  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 21), ["nakayama"])
    path.write_text(path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")

    record = storage.get_result("202603210601")
    records = storage.list_results(from_date=date(2026, 3, 21), to_date=date(2026, 3, 21), course="nakayama")
    page = storage.list_results_page(
        from_date=date(2026, 3, 21),
        to_date=date(2026, 3, 21),
        course="nakayama",
        limit=1,
        offset=1,
    )

    assert record is not None
    assert record.race_id == "202603210601"
    assert len(records) == 2
    assert page.total == 2
    assert page.limit == 1
    assert page.offset == 1
    assert len(page.items) == 1


@pytest.mark.asyncio
async def test_sqlite_storage_persists_and_reads_results(tmp_path):
    service = FakeService()
    storage = SQLiteRaceResultStorage(tmp_path / "results.sqlite")
    collector = PastResultCollector(service=service, storage=storage)  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 21), ["nakayama"])

    assert storage.has_race("202603210601") is True
    assert storage.get_result("202603210601") is not None
    assert len(storage.list_results(course="nakayama")) == 2
    page = storage.list_results_page(course="nakayama", limit=1, offset=0)
    assert page.total == 2
    assert len(page.items) == 1
