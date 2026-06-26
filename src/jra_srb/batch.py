from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path

from .models import RaceResult
from .service import JraService


class ResultStorage:
    def has_race(self, race_id: str) -> bool:
        raise NotImplementedError

    def write_result(self, target_date: date, course: str, race_no: int, result: RaceResult) -> None:
        raise NotImplementedError


@dataclass
class JsonlRaceResultStorage(ResultStorage):
    path: Path

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._known_race_ids = self._load_known_race_ids()

    def has_race(self, race_id: str) -> bool:
        return race_id in self._known_race_ids

    def write_result(self, target_date: date, course: str, race_no: int, result: RaceResult) -> None:
        record = {
            "race_id": result.race_id,
            "date": target_date.isoformat(),
            "course": course,
            "race_no": race_no,
            "result": result.model_dump(mode="json"),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._known_race_ids.add(result.race_id)

    def _load_known_race_ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        race_ids: set[str] = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            race_id = payload.get("race_id")
            if race_id:
                race_ids.add(race_id)
        return race_ids


class PastResultCollector:
    def __init__(
        self,
        service: JraService,
        storage: ResultStorage | None = None,
        retries: int = 0,
    ) -> None:
        self.service = service
        self.storage = storage
        self.retries = retries

    async def collect(self, from_date: date, to_date: date, courses: list[str]) -> None:
        current = from_date
        while current <= to_date:
            for course in courses:
                meeting = await self.service.get_meeting(current, course)
                if self.storage is None:
                    continue
                for race in meeting.races:
                    if self.storage.has_race(race.race_id):
                        continue
                    result = await self._fetch_result_with_retry(current, course, race.race_no)
                    self.storage.write_result(current, course, race.race_no, result)
            current += timedelta(days=1)

    async def _fetch_result_with_retry(self, target_date: date, course: str, race_no: int) -> RaceResult:
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return await self.service.get_race_result_by_number(target_date, course, race_no)
            except Exception as exc:  # pragma: no cover - exercised via retry test
                last_error = exc
        assert last_error is not None
        raise last_error
