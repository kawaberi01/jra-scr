from datetime import date

import pytest

from jra_srb.batch import PastResultCollector


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[date, str]] = []

    async def get_meeting(self, target_date: date, course: str) -> None:
        self.calls.append((target_date, course))


@pytest.mark.asyncio
async def test_collect_results_range_calls_service_for_each_day():
    service = FakeService()
    collector = PastResultCollector(service=service)  # type: ignore[arg-type]

    await collector.collect(date(2026, 3, 21), date(2026, 3, 22), ["nakayama", "hanshin"])

    assert service.calls == [
        (date(2026, 3, 21), "nakayama"),
        (date(2026, 3, 21), "hanshin"),
        (date(2026, 3, 22), "nakayama"),
        (date(2026, 3, 22), "hanshin"),
    ]
