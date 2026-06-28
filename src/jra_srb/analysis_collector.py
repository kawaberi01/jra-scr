from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .analysis_store import AnalysisSQLiteStore
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


class AnalysisCollector:
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
        current = options.from_date
        while current <= options.to_date:
            for course in options.courses:
                try:
                    meeting = await self.service.get_meeting(current, course)
                except Exception as exc:
                    failed = True
                    self.store.write_error(run_id, current, course, "meeting", exc)
                    continue
                for race in meeting.races:
                    self.store.write_race(current, course, race, source=meeting.source, fetched_at=meeting.fetched_at)
                    if options.include_card:
                        try:
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
                            try:
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
                    if options.include_results:
                        try:
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
            current += timedelta(days=1)
        self.store.finish_run(run_id, "failed" if failed else "succeeded")
        return run_id

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
