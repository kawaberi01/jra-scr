from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

from .models import CourseCode, RaceResult, StoredRaceResultPage, StoredRaceResultRecord
from .service import JraService


class ResultStorage:
    def has_race(self, race_id: str) -> bool:
        raise NotImplementedError

    def write_result(self, target_date: date, course: str, race_no: int, result: RaceResult) -> None:
        raise NotImplementedError

    def get_result(self, race_id: str) -> StoredRaceResultRecord | None:
        raise NotImplementedError

    def list_results(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        course: str | None = None,
    ) -> list[StoredRaceResultRecord]:
        raise NotImplementedError

    def list_results_page(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        course: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> StoredRaceResultPage:
        records = self.list_results(from_date=from_date, to_date=to_date, course=course)
        return StoredRaceResultPage(
            items=records[offset : offset + limit],
            total=len(records),
            limit=limit,
            offset=offset,
        )


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
        for payload in self._iter_payloads():
            race_id = payload.get("race_id")
            if isinstance(race_id, str) and race_id:
                race_ids.add(race_id)
        return race_ids

    def get_result(self, race_id: str) -> StoredRaceResultRecord | None:
        for record in self.list_results():
            if record.race_id == race_id:
                return record
        return None

    def list_results(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        course: str | None = None,
    ) -> list[StoredRaceResultRecord]:
        records: list[StoredRaceResultRecord] = []
        for payload in self._iter_payloads():
            record = self._to_record(payload)
            if record is None:
                continue
            if from_date is not None and record.date < from_date:
                continue
            if to_date is not None and record.date > to_date:
                continue
            if course is not None and record.course != course:
                continue
            records.append(record)
        return records

    def _iter_payloads(self) -> list[dict]:
        if not self.path.exists():
            return []
        payloads: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    @staticmethod
    def _to_record(payload: dict) -> StoredRaceResultRecord | None:
        try:
            return StoredRaceResultRecord(
                race_id=payload["race_id"],
                date=date.fromisoformat(payload["date"]),
                course=CourseCode(payload["course"]),
                race_no=int(payload["race_no"]),
                result=RaceResult.model_validate(payload["result"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class SQLiteRaceResultStorage(ResultStorage):
    path: Path

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def has_race(self, race_id: str) -> bool:
        return self.get_result(race_id) is not None

    def write_result(self, target_date: date, course: str, race_no: int, result: RaceResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into race_results
                (race_id, race_date, course, race_no, result_json)
                values (?, ?, ?, ?, ?)
                """,
                (
                    result.race_id,
                    target_date.isoformat(),
                    course,
                    race_no,
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def get_result(self, race_id: str) -> StoredRaceResultRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select race_id, race_date, course, race_no, result_json
                from race_results
                where race_id = ?
                """,
                (race_id,),
            ).fetchone()
        return self._row_to_record(row)

    def list_results(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        course: str | None = None,
    ) -> list[StoredRaceResultRecord]:
        where: list[str] = []
        params: list[str] = []
        if from_date is not None:
            where.append("race_date >= ?")
            params.append(from_date.isoformat())
        if to_date is not None:
            where.append("race_date <= ?")
            params.append(to_date.isoformat())
        if course is not None:
            where.append("course = ?")
            params.append(course)
        sql = "select race_id, race_date, course, race_no, result_json from race_results"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by race_date, course, race_no"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [record for row in rows if (record := self._row_to_record(row)) is not None]

    def list_results_page(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        course: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> StoredRaceResultPage:
        where, params = self._build_filters(from_date=from_date, to_date=to_date, course=course)
        sql = "select race_id, race_date, course, race_no, result_json from race_results"
        count_sql = "select count(*) from race_results"
        if where:
            clause = " where " + " and ".join(where)
            sql += clause
            count_sql += clause
        sql += " order by race_date, course, race_no limit ? offset ?"
        with self._connect() as conn:
            total = int(conn.execute(count_sql, params).fetchone()[0])
            rows = conn.execute(sql, [*params, limit, offset]).fetchall()
        return StoredRaceResultPage(
            items=[record for row in rows if (record := self._row_to_record(row)) is not None],
            total=total,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _build_filters(
        from_date: date | None = None,
        to_date: date | None = None,
        course: str | None = None,
    ) -> tuple[list[str], list[str]]:
        where: list[str] = []
        params: list[str] = []
        if from_date is not None:
            where.append("race_date >= ?")
            params.append(from_date.isoformat())
        if to_date is not None:
            where.append("race_date <= ?")
            params.append(to_date.isoformat())
        if course is not None:
            where.append("course = ?")
            params.append(course)
        return where, params

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists race_results (
                    race_id text primary key,
                    race_date text not null,
                    course text not null,
                    race_no integer not null,
                    result_json text not null
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_race_results_date_course
                on race_results (race_date, course)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _row_to_record(row: tuple | None) -> StoredRaceResultRecord | None:
        if row is None:
            return None
        race_id, race_date, course, race_no, result_json = row
        try:
            return StoredRaceResultRecord(
                race_id=race_id,
                date=date.fromisoformat(race_date),
                course=CourseCode(course),
                race_no=int(race_no),
                result=RaceResult.model_validate(json.loads(result_json)),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return None


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
