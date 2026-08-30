from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Callable
from uuid import uuid4

from .batch import PastResultCollector, ResultStorage
from .models import (
    ResultCollectionJobPage,
    ResultCollectionJobRequest,
    ResultCollectionJobStatus,
    ResultCollectionJobSummary,
    ResultStorageKind,
)
from .service import JraService

logger = logging.getLogger(__name__)

StorageFactory = Callable[[ResultStorageKind, str], ResultStorage]


class ResultCollectionJobRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self._jobs: dict[str, ResultCollectionJobSummary] = {}
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            self._load_jobs()
            self._recover_interrupted_jobs()

    def create_job(
        self,
        request: ResultCollectionJobRequest,
        storage: ResultStorageKind,
        output: str,
    ) -> ResultCollectionJobSummary:
        job = ResultCollectionJobSummary(
            job_id=str(uuid4()),
            status=ResultCollectionJobStatus.queued,
            from_date=request.from_date,
            to_date=request.to_date,
            courses=request.courses,
            storage=storage,
            output=output,
            retries=request.retries,
            created_at=datetime.now(UTC),
        )
        self._jobs[job.job_id] = job
        self._save(job)
        logger.info(
            "result_collection_job_created",
            extra={
                "job_id": job.job_id,
                "from_date": job.from_date.isoformat(),
                "to_date": job.to_date.isoformat(),
                "courses": [str(course) for course in job.courses],
                "storage": str(job.storage),
                "output": job.output,
            },
        )
        return job

    def list_jobs(self) -> ResultCollectionJobPage:
        items = sorted(self._jobs.values(), key=lambda job: job.created_at)
        return ResultCollectionJobPage(items=items, total=len(items))

    def get_job(self, job_id: str) -> ResultCollectionJobSummary:
        job = self._jobs.get(job_id)
        if job is None:
            raise LookupError(f"job not found for job_id={job_id}")
        return job

    async def run_job(
        self,
        job_id: str,
        service: JraService,
        storage_factory: StorageFactory,
    ) -> None:
        job = self.get_job(job_id)
        self._update(
            job_id,
            status=ResultCollectionJobStatus.running,
            started_at=datetime.now(UTC),
            message="collection started",
            error=None,
        )
        logger.info("result_collection_job_started", extra={"job_id": job_id})
        try:
            storage = storage_factory(job.storage, job.output)
            collector = PastResultCollector(
                service=service,
                storage=storage,
                retries=job.retries,
            )
            await collector.collect(
                from_date=job.from_date,
                to_date=job.to_date,
                courses=[str(course) for course in job.courses],
            )
        except Exception as exc:
            self._update(
                job_id,
                status=ResultCollectionJobStatus.failed,
                finished_at=datetime.now(UTC),
                message="collection failed",
                error=str(exc),
            )
            logger.exception("result_collection_job_failed", extra={"job_id": job_id})
            return
        self._update(
            job_id,
            status=ResultCollectionJobStatus.succeeded,
            finished_at=datetime.now(UTC),
            message="collection succeeded",
            error=None,
        )
        logger.info("result_collection_job_succeeded", extra={"job_id": job_id})

    def clear(self) -> None:
        self._jobs.clear()
        if self.path is not None:
            with self._connect() as conn:
                conn.execute("delete from result_collection_jobs")

    def _update(self, job_id: str, **changes: object) -> None:
        job = self.get_job(job_id)
        updated = job.model_copy(update=changes)
        self._jobs[job_id] = updated
        self._save(updated)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists result_collection_jobs (
                    job_id text primary key,
                    status text not null,
                    from_date text not null,
                    to_date text not null,
                    courses_json text not null,
                    storage text not null,
                    output text not null,
                    retries integer not null,
                    created_at text not null,
                    started_at text,
                    finished_at text,
                    message text,
                    error text
                )
                """
            )

    def _load_jobs(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select job_id, status, from_date, to_date, courses_json, storage, output,
                       retries, created_at, started_at, finished_at, message, error
                from result_collection_jobs
                """
            ).fetchall()
        self._jobs = {
            job.job_id: job
            for row in rows
            if (job := self._row_to_job(row)) is not None
        }

    def _recover_interrupted_jobs(self) -> None:
        for job in list(self._jobs.values()):
            if job.status == ResultCollectionJobStatus.running:
                self._update(
                    job.job_id,
                    status=ResultCollectionJobStatus.failed,
                    finished_at=datetime.now(UTC),
                    message="collection interrupted by process restart",
                    error="collection interrupted by process restart",
                )

    def _save(self, job: ResultCollectionJobSummary) -> None:
        if self.path is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                insert into result_collection_jobs
                (job_id, status, from_date, to_date, courses_json, storage, output, retries,
                 created_at, started_at, finished_at, message, error)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(job_id) do update set
                    status = excluded.status,
                    from_date = excluded.from_date,
                    to_date = excluded.to_date,
                    courses_json = excluded.courses_json,
                    storage = excluded.storage,
                    output = excluded.output,
                    retries = excluded.retries,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    message = excluded.message,
                    error = excluded.error
                """,
                (
                    job.job_id,
                    str(job.status),
                    job.from_date.isoformat(),
                    job.to_date.isoformat(),
                    json.dumps([str(course) for course in job.courses]),
                    str(job.storage),
                    job.output,
                    job.retries,
                    job.created_at.isoformat(),
                    job.started_at.isoformat() if job.started_at is not None else None,
                    job.finished_at.isoformat() if job.finished_at is not None else None,
                    job.message,
                    job.error,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        return sqlite3.connect(self.path)

    @staticmethod
    def _row_to_job(row: tuple[object, ...]) -> ResultCollectionJobSummary | None:
        try:
            return ResultCollectionJobSummary(
                job_id=str(row[0]),
                status=ResultCollectionJobStatus(str(row[1])),
                from_date=str(row[2]),
                to_date=str(row[3]),
                courses=json.loads(str(row[4])),
                storage=ResultStorageKind(str(row[5])),
                output=str(row[6]),
                retries=int(row[7]),
                created_at=datetime.fromisoformat(str(row[8])),
                started_at=datetime.fromisoformat(str(row[9])) if row[9] is not None else None,
                finished_at=datetime.fromisoformat(str(row[10])) if row[10] is not None else None,
                message=str(row[11]) if row[11] is not None else None,
                error=str(row[12]) if row[12] is not None else None,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.error("result_collection_job_invalid_row")
            return None
