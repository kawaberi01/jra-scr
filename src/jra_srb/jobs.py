from __future__ import annotations

from datetime import UTC, datetime
import logging
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
    def __init__(self) -> None:
        self._jobs: dict[str, ResultCollectionJobSummary] = {}

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

    def _update(self, job_id: str, **changes: object) -> None:
        job = self.get_job(job_id)
        self._jobs[job_id] = job.model_copy(update=changes)
