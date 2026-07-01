from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
import json
from typing import Any

from .analysis_store import AnalysisSQLiteStore
from .models import RaceCard
from .service import JraService


@dataclass(frozen=True)
class AnalysisRaceTarget:
    race_id: str
    race_date: date
    course: str
    race_no: int
    runner_count: int


@dataclass(frozen=True)
class RunnerBackfillOptions:
    from_date: date
    to_date: date
    courses: list[str]
    only_missing: bool = True
    retries: int = 0
    min_interval_seconds: float = 0.0
    limit: int | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class RunnerBackfillSummary:
    run_id: str
    target_count: int
    processed_count: int
    written_count: int
    failed_count: int
    skipped_count: int
    dry_run: bool
    status: str


@dataclass(frozen=True)
class AnalysisJoinSample:
    race_id: str
    horse_no: str
    horse_name: str
    jockey: str | None
    trainer: str | None
    sex_age: str | None
    weight_carried: str | None


@dataclass(frozen=True)
class AnalysisJoinVerification:
    races: int
    runners: int
    race_results: int
    result_entries: int
    payouts: int
    races_with_runners: int
    result_runner_join_rows: int
    payout_runner_race_join_rows: int
    missing_runner_races: int
    latest_run_errors: list[dict[str, Any]] = field(default_factory=list)
    samples: list[AnalysisJoinSample] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        required_counts = [
            self.races,
            self.runners,
            self.race_results,
            self.result_entries,
            self.payouts,
            self.races_with_runners,
            self.result_runner_join_rows,
            self.payout_runner_race_join_rows,
        ]
        return all(value > 0 for value in required_counts) and self.missing_runner_races == 0


class AnalysisRunnerBackfiller:
    def __init__(self, service: JraService, store: AnalysisSQLiteStore) -> None:
        self.service = service
        self.store = store

    async def backfill(self, options: RunnerBackfillOptions) -> RunnerBackfillSummary:
        targets = self.store.list_races_for_runner_backfill(
            from_date=options.from_date,
            to_date=options.to_date,
            courses=options.courses,
            only_missing=options.only_missing,
            limit=options.limit,
        )
        run_id = "dry-run"
        if not options.dry_run:
            run_id = self.store.create_run(
                from_date=options.from_date,
                to_date=options.to_date,
                courses=options.courses,
                include_card=True,
                include_odds=False,
                include_results=False,
                odds_timing="final_or_near_final",
            )
        failed_count = 0
        written_count = 0
        skipped_count = 0
        for index, target in enumerate(targets):
            if options.dry_run:
                skipped_count += 1
            else:
                try:
                    card = await self._with_retry(
                        options.retries,
                        self.service.get_race_card_by_number,
                        target.race_date,
                        target.course,
                        target.race_no,
                    )
                    self._validate_card_target(target, card)
                except Exception as exc:
                    failed_count += 1
                    self.store.write_error(
                        run_id,
                        target.race_date,
                        target.course,
                        "card",
                        exc,
                        race_id=target.race_id,
                        race_no=target.race_no,
                    )
                else:
                    self.store.write_card(target.race_date, target.course, target.race_no, card)
                    written_count += 1
            if not options.dry_run and options.min_interval_seconds > 0 and index < len(targets) - 1:
                await asyncio.sleep(options.min_interval_seconds)

        status = "dry-run" if options.dry_run else "failed" if failed_count else "succeeded"
        if not options.dry_run:
            self.store.finish_run(run_id, status)
        return RunnerBackfillSummary(
            run_id=run_id,
            target_count=len(targets),
            processed_count=len(targets) - skipped_count,
            written_count=written_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            dry_run=options.dry_run,
            status=status,
        )

    @staticmethod
    async def _with_retry(retries: int, func, *args):
        last_error: Exception | None = None
        for _ in range(retries + 1):
            try:
                return await func(*args)
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    @staticmethod
    def _validate_card_target(target: AnalysisRaceTarget, card: RaceCard) -> None:
        if card.race_id != target.race_id:
            raise ValueError(f"card race_id mismatch: expected={target.race_id} actual={card.race_id}")


class AnalysisJoinVerifier:
    def __init__(self, store: AnalysisSQLiteStore) -> None:
        self.store = store

    def verify(self, from_date: date, to_date: date, sample_size: int) -> AnalysisJoinVerification:
        return self.store.verify_analysis_joins(from_date=from_date, to_date=to_date, sample_size=sample_size)


def format_backfill_summary(summary: RunnerBackfillSummary) -> str:
    lines = [
        f"run_id={summary.run_id}",
        f"status={summary.status}",
        f"dry_run={int(summary.dry_run)}",
        f"targets={summary.target_count}",
        f"processed={summary.processed_count}",
        f"written={summary.written_count}",
        f"failed={summary.failed_count}",
        f"skipped={summary.skipped_count}",
    ]
    return "\n".join(lines)


def format_join_verification(result: AnalysisJoinVerification) -> str:
    lines = [
        f"races={result.races}",
        f"runners={result.runners}",
        f"race_results={result.race_results}",
        f"result_entries={result.result_entries}",
        f"payouts={result.payouts}",
        f"races_with_runners={result.races_with_runners}",
        f"result_runner_join_rows={result.result_runner_join_rows}",
        f"payout_runner_race_join_rows={result.payout_runner_race_join_rows}",
        f"missing_runner_races={result.missing_runner_races}",
        "latest_run_errors=" + json.dumps(result.latest_run_errors, ensure_ascii=False),
    ]
    for sample in result.samples:
        lines.append(
            "sample="
            + "|".join(
                [
                    sample.race_id,
                    sample.horse_no,
                    sample.horse_name,
                    sample.jockey or "",
                    sample.trainer or "",
                    sample.sex_age or "",
                    sample.weight_carried or "",
                ]
            )
        )
    return "\n".join(lines)
