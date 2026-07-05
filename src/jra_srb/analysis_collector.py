from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from time import monotonic

from .analysis_store import AnalysisSQLiteStore
from .models import MeetingSnapshot
from .service import JraService, SUPPORTED_JRA_BET_TYPES


@dataclass
class AnalysisCollectionOptions:
    from_date: date
    to_date: date
    courses: list[str]
    include_card: bool = True
    include_odds: bool = True
    include_results: bool = True
    odds_timing: str = "final_or_near_final"
    bet_types: list[str] | None = None
    retries: int = 0
    min_interval_seconds: float = 0.0
    max_live_requests: int | None = None
    skip_existing: bool = False


class AnalysisCollector:
    AUTO_COURSE_TOKENS = {"all", "*", "auto"}

    def __init__(self, service: JraService, store: AnalysisSQLiteStore) -> None:
        self.service = service
        self.store = store

    async def collect(self, options: AnalysisCollectionOptions) -> str:
        run_id = self.store.create_run(
            from_date=options.from_date,
            to_date=options.to_date,
            courses=options.courses,
            include_card=options.include_card,
            include_odds=options.include_odds,
            include_results=options.include_results,
            odds_timing=options.odds_timing,
        )
        failed = False
        live_requests = 0
        live_request_limit_reached = False
        last_request_started: float | None = None
        current = options.from_date
        while current <= options.to_date:
            (
                last_request_started,
                live_requests,
                live_request_limit_reached,
                meetings,
                meeting_errors,
            ) = await self._load_meetings(
                run_id,
                current,
                options.courses,
                options.min_interval_seconds,
                options.max_live_requests,
                live_requests,
                last_request_started,
            )
            if live_request_limit_reached:
                break
            if meeting_errors:
                failed = True
            if meetings is None:
                current += timedelta(days=1)
                continue
            for meeting in meetings:
                course = meeting.course
                for race in meeting.races:
                    self.store.write_race(current, course, race, source=meeting.source, fetched_at=meeting.fetched_at)
                    if options.include_card:
                        if options.skip_existing and self.store.has_card(race.race_id):
                            continue
                        try:
                            (
                                last_request_started,
                                live_requests,
                                live_request_limit_reached,
                            ) = await self._prepare_live_request(
                                last_request_started,
                                options.min_interval_seconds,
                                options.max_live_requests,
                                live_requests,
                            )
                            if live_request_limit_reached:
                                break
                            card = await self._with_retry(
                                options.retries,
                                self.service.get_race_card_by_number,
                                current,
                                course,
                                race.race_no,
                            )
                        except Exception as exc:
                            failed = True
                            self.store.write_error(run_id, current, course, "card", exc, race.race_id, race.race_no)
                        else:
                            self.store.write_card(current, course, race.race_no, card)
                    if options.include_odds:
                        for bet_type in options.bet_types or list(SUPPORTED_JRA_BET_TYPES):
                            if options.skip_existing and self.store.has_odds_snapshot(
                                race.race_id,
                                bet_type,
                                options.odds_timing,
                            ):
                                continue
                            try:
                                (
                                    last_request_started,
                                    live_requests,
                                    live_request_limit_reached,
                                ) = await self._prepare_live_request(
                                    last_request_started,
                                    options.min_interval_seconds,
                                    options.max_live_requests,
                                    live_requests,
                                )
                                if live_request_limit_reached:
                                    break
                                odds = await self._with_retry(
                                    options.retries,
                                    self.service.get_race_odds_by_number,
                                    current,
                                    course,
                                    race.race_no,
                                    bet_type,
                                )
                            except Exception as exc:
                                failed = True
                                self.store.write_error(
                                    run_id,
                                    current,
                                    course,
                                    f"odds:{bet_type}",
                                    exc,
                                    race.race_id,
                                    race.race_no,
                                )
                            else:
                                self.store.write_odds(odds, bet_type=bet_type, odds_timing=options.odds_timing)
                        if live_request_limit_reached:
                            break
                    if options.include_results:
                        if options.skip_existing and self.store.has_result(race.race_id):
                            continue
                        try:
                            (
                                last_request_started,
                                live_requests,
                                live_request_limit_reached,
                            ) = await self._prepare_live_request(
                                last_request_started,
                                options.min_interval_seconds,
                                options.max_live_requests,
                                live_requests,
                            )
                            if live_request_limit_reached:
                                break
                            result = await self._with_retry(
                                options.retries,
                                self.service.get_race_result_by_number,
                                current,
                                course,
                                race.race_no,
                            )
                        except Exception as exc:
                            failed = True
                            self.store.write_error(run_id, current, course, "result", exc, race.race_id, race.race_no)
                        else:
                            self.store.write_result(result)
                    if live_request_limit_reached:
                        break
                if live_request_limit_reached:
                    break
            if live_request_limit_reached:
                break
            current += timedelta(days=1)
        status = "failed" if failed else "partial" if live_request_limit_reached else "succeeded"
        self.store.finish_run(run_id, status)
        return run_id

    async def _load_meetings(
        self,
        run_id: str,
        target_date: date,
        courses: list[str],
        min_interval_seconds: float,
        max_live_requests: int | None,
        live_requests: int,
        last_request_started: float | None,
    ) -> tuple[float | None, int, bool, list[MeetingSnapshot] | None, bool]:
        if self._should_auto_discover_courses(courses):
            try:
                last_request_started, live_requests, limit_reached = await self._prepare_live_request(
                    last_request_started,
                    min_interval_seconds,
                    max_live_requests,
                    live_requests,
                )
                if limit_reached:
                    return last_request_started, live_requests, True, None, False
                return last_request_started, live_requests, False, await self.service.get_meetings_for_date(target_date), False
            except Exception as exc:
                self.store.write_error(run_id, target_date, "all", "meeting-list", exc)
                return last_request_started, live_requests, False, None, True

        meetings: list[MeetingSnapshot] = []
        had_error = False
        for course in courses:
            try:
                last_request_started, live_requests, limit_reached = await self._prepare_live_request(
                    last_request_started,
                    min_interval_seconds,
                    max_live_requests,
                    live_requests,
                )
                if limit_reached:
                    return last_request_started, live_requests, True, meetings, had_error
                meetings.append(await self.service.get_meeting(target_date, course))
            except Exception as exc:
                had_error = True
                self.store.write_error(run_id, target_date, course, "meeting", exc)
        return last_request_started, live_requests, False, meetings, had_error

    @classmethod
    def _should_auto_discover_courses(cls, courses: list[str]) -> bool:
        return len(courses) == 1 and courses[0].strip().lower() in cls.AUTO_COURSE_TOKENS

    @staticmethod
    async def _wait_for_interval(last_request_started: float | None, min_interval_seconds: float) -> float:
        if last_request_started is not None and min_interval_seconds > 0:
            elapsed = monotonic() - last_request_started
            remaining = min_interval_seconds - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
        return monotonic()

    @classmethod
    async def _prepare_live_request(
        cls,
        last_request_started: float | None,
        min_interval_seconds: float,
        max_live_requests: int | None,
        live_requests: int,
    ) -> tuple[float | None, int, bool]:
        if max_live_requests is not None and live_requests >= max_live_requests:
            return last_request_started, live_requests, True
        return await cls._wait_for_interval(last_request_started, min_interval_seconds), live_requests + 1, False

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
