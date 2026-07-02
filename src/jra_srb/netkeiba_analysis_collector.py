from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import monotonic

from .analysis_store import AnalysisSQLiteStore
from .netkeiba_service import NetkeibaService


@dataclass(frozen=True)
class NetkeibaRaceTarget:
    netkeiba_race_id: str
    jra_race_id: str | None = None
    race_date: date | None = None
    course: str | None = None
    race_no: int | None = None
    mapping_status: str = "mapped"
    mapping_note: str | None = None

    @property
    def is_mappable(self) -> bool:
        return bool(self.netkeiba_race_id) and self.mapping_status in {"mapped", "mapped_estimated"}


@dataclass(frozen=True)
class NetkeibaResultCollectionOptions:
    from_date: date
    to_date: date
    mapping_csv: Path
    max_live_requests: int = 30
    min_interval_seconds: float = 10.0
    refresh: bool = False
    retries: int = 0
    dry_run: bool = False
    limit: int | None = None


@dataclass(frozen=True)
class NetkeibaResultCollectionSummary:
    run_id: str | None
    target_count: int
    saved_count: int
    unsaved_count: int
    planned_request_count: int
    unmappable_count: int
    collected_count: int
    skipped_count: int
    failed_count: int
    live_request_limit_reached: bool
    dry_run: bool = False


class NetkeibaAnalysisCollector:
    def __init__(self, service: NetkeibaService, store: AnalysisSQLiteStore) -> None:
        self.service = service
        self.store = store

    async def collect_results(self, options: NetkeibaResultCollectionOptions) -> NetkeibaResultCollectionSummary:
        targets = load_netkeiba_race_targets(
            options.mapping_csv,
            options.from_date,
            options.to_date,
            limit=options.limit,
        )
        inspection = self._inspect_targets(targets, options.refresh, options.max_live_requests)
        if options.dry_run:
            return NetkeibaResultCollectionSummary(
                run_id=None,
                target_count=inspection["target_count"],
                saved_count=inspection["saved_count"],
                unsaved_count=inspection["unsaved_count"],
                planned_request_count=inspection["planned_request_count"],
                unmappable_count=inspection["unmappable_count"],
                collected_count=0,
                skipped_count=inspection["saved_count"],
                failed_count=0,
                live_request_limit_reached=inspection["live_request_limit_reached"],
                dry_run=True,
            )
        run_id = self.store.create_run(
            from_date=options.from_date,
            to_date=options.to_date,
            courses=["netkeiba"],
            include_card=False,
            include_odds=False,
            include_results=True,
            odds_timing="netkeiba",
        )
        collected = 0
        skipped = inspection["saved_count"]
        failed = 0
        live_requests = 0
        live_request_limit_reached = False
        last_request_started: float | None = None

        for target in targets:
            if not target.is_mappable:
                continue
            if not options.refresh and self.store.has_netkeiba_result(target.netkeiba_race_id):
                continue
            if live_requests >= options.max_live_requests:
                live_request_limit_reached = True
                break
            last_request_started = await self._wait_for_interval(last_request_started, options.min_interval_seconds)
            live_requests += 1
            try:
                result = await self._with_retry(
                    options.retries,
                    self.service.get_race_result,
                    target.netkeiba_race_id,
                )
            except Exception as exc:
                failed += 1
                self.store.write_error(
                    run_id=run_id,
                    target_date=target.race_date or options.from_date,
                    course=target.course or "netkeiba",
                    stage="netkeiba-result",
                    exc=exc,
                    race_id=target.jra_race_id or target.netkeiba_race_id,
                    race_no=target.race_no,
                )
                continue
            self.store.write_netkeiba_result(result, jra_race_id=target.jra_race_id)
            collected += 1

        status = "failed" if failed else "succeeded"
        self.store.finish_run(run_id, status)
        return NetkeibaResultCollectionSummary(
            run_id=run_id,
            target_count=inspection["target_count"],
            saved_count=inspection["saved_count"],
            unsaved_count=inspection["unsaved_count"],
            planned_request_count=inspection["planned_request_count"],
            unmappable_count=inspection["unmappable_count"],
            collected_count=collected,
            skipped_count=skipped,
            failed_count=failed,
            live_request_limit_reached=live_request_limit_reached,
        )

    def _inspect_targets(
        self,
        targets: list[NetkeibaRaceTarget],
        refresh: bool,
        max_live_requests: int,
    ) -> dict[str, int | bool]:
        saved = 0
        unsaved = 0
        unmappable = 0
        for target in targets:
            if not target.is_mappable:
                unmappable += 1
                continue
            if not refresh and self.store.has_netkeiba_result(target.netkeiba_race_id):
                saved += 1
            else:
                unsaved += 1
        planned = min(unsaved, max_live_requests)
        return {
            "target_count": len(targets),
            "saved_count": saved,
            "unsaved_count": unsaved,
            "planned_request_count": planned,
            "unmappable_count": unmappable,
            "live_request_limit_reached": unsaved > max_live_requests,
        }

    @staticmethod
    async def _wait_for_interval(last_request_started: float | None, min_interval_seconds: float) -> float:
        if last_request_started is not None and min_interval_seconds > 0:
            elapsed = monotonic() - last_request_started
            remaining = min_interval_seconds - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
        return monotonic()

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


def load_netkeiba_race_targets(
    mapping_csv: Path,
    from_date: date,
    to_date: date,
    limit: int | None = None,
) -> list[NetkeibaRaceTarget]:
    targets: list[NetkeibaRaceTarget] = []
    with mapping_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("mapping CSV must include netkeiba_race_id")
        fieldnames = set(reader.fieldnames)
        if "netkeiba_race_id" not in fieldnames:
            raise ValueError("mapping CSV must include netkeiba_race_id")
        for row in reader:
            if limit is not None and len(targets) >= limit:
                break
            race_date = _parse_date(row.get("race_date"))
            if race_date is not None and not (from_date <= race_date <= to_date):
                continue
            netkeiba_race_id = (row.get("netkeiba_race_id") or "").strip()
            targets.append(
                NetkeibaRaceTarget(
                    netkeiba_race_id=netkeiba_race_id,
                    jra_race_id=_clean_optional(row.get("jra_race_id")),
                    race_date=race_date,
                    course=_clean_optional(row.get("course")),
                    race_no=_parse_int(row.get("race_no")),
                    mapping_status=_clean_optional(row.get("mapping_status")) or ("mapped" if netkeiba_race_id else "unmapped"),
                    mapping_note=_clean_optional(row.get("mapping_note")),
                )
            )
    return targets


def _parse_date(value: str | None) -> date | None:
    cleaned = _clean_optional(value)
    if cleaned is None:
        return None
    return date.fromisoformat(cleaned)


def _parse_int(value: str | None) -> int | None:
    cleaned = _clean_optional(value)
    if cleaned is None:
        return None
    return int(cleaned)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
