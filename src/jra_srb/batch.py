from __future__ import annotations

from datetime import date, timedelta

from .service import JraService


class PastResultCollector:
    def __init__(self, service: JraService) -> None:
        self.service = service

    async def collect(self, from_date: date, to_date: date, courses: list[str]) -> None:
        current = from_date
        while current <= to_date:
            for course in courses:
                await self.service.get_meeting(current, course)
            current += timedelta(days=1)
        # TODO: Persist collected results and payouts to a pluggable storage backend.
