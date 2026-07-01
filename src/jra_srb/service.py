from __future__ import annotations

from datetime import UTC, date, datetime
import logging
from typing import Iterable

from .cache import TTLCache
from .config import load_parser_config
from .errors import BadRequestError, ResourceNotFoundError
from .extractors import (
    parse_calendar_meetings,
    parse_meeting_races,
    parse_jra_table_odds,
    parse_jra_trifecta_odds,
    parse_jra_win_place_odds,
    parse_odds_navigation,
    parse_race_card,
    parse_race_odds,
    parse_result_page_as_race_card,
    parse_result_month_navigation,
    parse_result_race_navigation,
    parse_race_result,
    parse_race_summaries,
)
from .models import MeetingRace, MeetingSnapshot, RaceCard, RaceOdds, RaceResult, RaceSummary
from .navigation import COURSE_NAMES, JraNavigation
from .provider import BaseProvider, FixtureProvider, HttpProvider

logger = logging.getLogger(__name__)


COURSE_CODE_TO_NAME = {
    "01": "sapporo",
    "02": "hakodate",
    "03": "fukushima",
    "04": "niigata",
    "05": "tokyo",
    "06": "nakayama",
    "07": "chukyo",
    "08": "kyoto",
    "09": "hanshin",
    "10": "kokura",
}

COURSE_NAME_TO_CODE = {value: key for key, value in COURSE_CODE_TO_NAME.items()}

SUPPORTED_BULK_BET_TYPES = {"win", "quinella", "trifecta"}
SUPPORTED_JRA_BET_TYPES = ("win", "quinella", "wide", "exacta", "trio", "trifecta")


class JraService:
    def __init__(self, provider: BaseProvider | None = None, cache: TTLCache | None = None) -> None:
        self.provider = provider or HttpProvider()
        self.cache = cache or TTLCache()
        self.navigation = JraNavigation()

    async def check_upstream(self) -> dict[str, str]:
        page = await self.provider.check_upstream()
        return {"status": "ok", "source": page.source}

    async def get_races(self, target_date: date, course: str | None = None) -> list[RaceSummary]:
        logger.info("get_races", extra={"target_date": target_date.isoformat(), "course": course})
        cache_key = f"races:{target_date.isoformat()}:{course or '*'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if not self._is_fixture_provider():
            meetings = [await self.get_meeting(target_date, course)] if course else await self._get_meetings_for_date(target_date)
            races = [
                RaceSummary(
                    race_id=race.race_id,
                    race_number=f"{race.race_no}R",
                    name=race.race_name or f"{race.race_no}R",
                    course=meeting.course,
                    start_time=race.start_time,
                )
                for meeting in meetings
                for race in meeting.races
            ]
            self.cache.set(cache_key, races, ttl_seconds=60)
            return races
        page = await self.provider.fetch_races(target_date, course=course)
        races = parse_race_summaries(page.content, load_parser_config("races"))
        self.cache.set(cache_key, races, ttl_seconds=60)
        return races

    async def get_race_card(self, race_id: str) -> RaceCard:
        logger.info("get_race_card", extra={"race_id": race_id})
        if not self._is_fixture_provider():
            target_date, course, race_no = self._split_race_id(race_id)
            return await self.get_race_card_by_number(target_date, course, race_no)
        cache_key = f"card:{race_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_race_card(race_id)
        parsed = parse_race_card(page.content, load_parser_config("race_card"))
        card = RaceCard(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        self.cache.set(cache_key, card, ttl_seconds=180)
        return card

    async def get_race_odds(
        self,
        race_id: str,
        bet_types: Iterable[str] | None = None,
        bet_type: str | None = None,
        combination: list[str] | None = None,
        refresh: bool = False,
    ) -> RaceOdds:
        logger.info(
            "get_race_odds",
            extra={"race_id": race_id, "bet_type": bet_type, "bet_types": list(bet_types or [])},
        )
        if bet_type is not None:
            return await self._get_jra_race_odds(
                race_id=race_id,
                bet_type=bet_type,
                combination=combination,
                refresh=refresh,
            )
        requested = list(bet_types or [])
        if not self._is_fixture_provider():
            if not requested:
                requested = list(SUPPORTED_JRA_BET_TYPES)
            return await self._get_jra_race_odds_bundle(race_id, requested, refresh=refresh)
        cache_key = f"odds:{race_id}:{','.join(requested) if requested else '*'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        if requested and not set(requested).issubset(SUPPORTED_BULK_BET_TYPES):
            target_date, course, race_no = self._split_race_id(race_id)
            meeting = await self.get_meeting(target_date, course)
            race = next((item for item in meeting.races if item.race_no == race_no), None)
            if race is None:
                raise ResourceNotFoundError(f"race not found for race_id={race_id}")
            if race.odds_cname is None:
                raise ResourceNotFoundError(f"odds entry cname not found for race_id={race_id}")
            odds = {}
            for requested_bet_type in requested:
                item = await self._get_jra_race_odds(
                    race_id=race_id,
                    bet_type=requested_bet_type,
                    combination=None,
                    refresh=refresh,
                    initial_cname=race.odds_cname,
                )
                odds[requested_bet_type] = item.entries
            result = RaceOdds(
                race_id=race_id,
                odds=odds,
                fetched_at=datetime.now(UTC),
                source=meeting.source,
            )
            self.cache.set(cache_key, result, ttl_seconds=45)
            return result
        page = await self.provider.fetch_race_odds(race_id)
        odds = parse_race_odds(page.content, load_parser_config("race_odds"))
        if requested:
            odds = {bet_type: odds.get(bet_type, []) for bet_type in requested}
        result = RaceOdds(
            race_id=race_id,
            odds=odds,
            fetched_at=datetime.now(UTC),
            source=page.source,
        )
        self.cache.set(cache_key, result, ttl_seconds=45)
        return result

    async def get_race_result(self, race_id: str) -> RaceResult:
        logger.info("get_race_result", extra={"race_id": race_id})
        if not self._is_fixture_provider():
            target_date, course, race_no = self._split_race_id(race_id)
            return await self.get_race_result_by_number(target_date, course, race_no)
        cache_key = f"result:{race_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_race_result(race_id)
        parsed = parse_race_result(page.content, load_parser_config("race_result"))
        result = RaceResult(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        self.cache.set(cache_key, result, ttl_seconds=3600)
        return result

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
        logger.info(
            "get_race_result_by_number",
            extra={"target_date": target_date.isoformat(), "course": course, "race_no": race_no},
        )
        cache_key = f"result-by-number:{target_date.isoformat()}:{course}:{race_no}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        race_id = self._join_race_id(target_date, course, race_no)
        if self._is_fixture_provider():
            page = await self.provider.fetch_race_result(race_id)
        else:
            page = await self._load_result_race_page(target_date, course, race_no)
        parsed = parse_race_result(page.content, load_parser_config("race_result"))
        result = RaceResult(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        result = await self._enrich_result_with_card_jockeys(result, target_date, course, race_no)
        self.cache.set(cache_key, result, ttl_seconds=3600)
        return result

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        logger.info("get_meeting", extra={"target_date": target_date.isoformat(), "course": course})
        cache_key = f"meeting:{target_date.isoformat()}:{course}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        meeting = await self._load_meeting_for_date(target_date, course)
        self.cache.set(cache_key, meeting, ttl_seconds=60)
        return meeting

    async def get_meetings_for_date(self, target_date: date) -> list[MeetingSnapshot]:
        logger.info("get_meetings_for_date", extra={"target_date": target_date.isoformat()})
        if self._is_fixture_provider():
            courses = {summary.course for summary in await self.get_races(target_date) if summary.course}
            return [await self.get_meeting(target_date, course) for course in sorted(courses)]
        meetings = await self._get_meetings_for_date(target_date)
        if meetings:
            return meetings
        meetings = await self._get_meetings_for_date_from_kind(target_date, kind="payout")
        if meetings:
            return meetings
        meetings = await self._get_meetings_for_date_from_result_selection(target_date)
        if meetings:
            return meetings
        return await self._get_meetings_for_date_from_calendar(target_date)

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int) -> RaceCard:
        logger.info(
            "get_race_card_by_number",
            extra={"target_date": target_date.isoformat(), "course": course, "race_no": race_no},
        )
        meeting = await self.get_meeting(target_date, course)
        race = next((item for item in meeting.races if item.race_no == race_no), None)
        if race is None:
            raise ResourceNotFoundError(f"race not found: {course} {target_date} {race_no}")
        cache_key = f"card-by-number:{target_date.isoformat()}:{course}:{race_no}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        if race.card_cname is None:
            page = await self._load_result_race_page(target_date, course, race_no)
            parsed = parse_result_page_as_race_card(page.content)
        else:
            page = await self.provider.fetch_jradb("/JRADB/accessD.html", race.card_cname)
            parsed = parse_race_card(page.content, load_parser_config("race_card"))
        card = RaceCard(
            race_id=race.race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        self.cache.set(cache_key, card, ttl_seconds=180)
        return card

    async def get_race_odds_by_number(
        self,
        target_date: date,
        course: str,
        race_no: int,
        bet_type: str,
        combination: list[str] | None = None,
        refresh: bool = False,
    ) -> RaceOdds:
        logger.info(
            "get_race_odds_by_number",
            extra={
                "target_date": target_date.isoformat(),
                "course": course,
                "race_no": race_no,
                "bet_type": bet_type,
            },
        )
        meeting = await self.get_meeting(target_date, course)
        race = next((item for item in meeting.races if item.race_no == race_no), None)
        if race is None:
            raise ResourceNotFoundError(f"race not found: {course} {target_date} {race_no}")
        return await self._get_jra_race_odds(
            race_id=race.race_id,
            bet_type=bet_type,
            combination=combination,
            refresh=refresh,
            initial_cname=race.odds_cname,
        )

    async def _get_jra_race_odds(
        self,
        race_id: str,
        bet_type: str,
        combination: list[str] | None = None,
        refresh: bool = False,
        initial_cname: str | None = None,
    ) -> RaceOdds:
        cache_key = f"jra-odds:{race_id}:{bet_type}"
        cached = self.cache.get(cache_key)
        if cached is not None and not refresh:
            return self._filter_entries(cached, combination, cache_hit=True)
        if initial_cname is None:
            target_date, course, race_no = self._split_race_id(race_id)
            meeting = await self.get_meeting(target_date, course)
            race = next((item for item in meeting.races if item.race_no == race_no), None)
            if race is None:
                raise ResourceNotFoundError(f"race not found for race_id={race_id}")
            initial_cname = race.odds_cname
        if initial_cname is None:
            raise ResourceNotFoundError(f"odds entry cname not found for race_id={race_id}")
        root_page = await self.provider.post_jradb("/JRADB/accessO.html", initial_cname)
        navigation = parse_odds_navigation(root_page.content)
        target_cname = navigation.get(bet_type, initial_cname if bet_type == "win" else None)
        if target_cname is None:
            raise BadRequestError(f"unsupported bet_type={bet_type}")
        page = await self.provider.post_jradb("/JRADB/accessO.html", target_cname)
        if bet_type == "win":
            entries = parse_jra_win_place_odds(page.content)
        elif bet_type == "quinella":
            entries = parse_jra_table_odds(page.content, bet_type="quinella", leg_count=2)
        elif bet_type == "wide":
            entries = parse_jra_table_odds(page.content, bet_type="wide", leg_count=2)
        elif bet_type == "exacta":
            entries = parse_jra_table_odds(page.content, bet_type="exacta", leg_count=2)
        elif bet_type == "trio":
            entries = parse_jra_table_odds(page.content, bet_type="trio", leg_count=3)
        elif bet_type == "trifecta":
            entries = parse_jra_trifecta_odds(page.content)
        else:
            raise BadRequestError(f"unsupported bet_type={bet_type}")
        result = RaceOdds(
            race_id=race_id,
            bet_type=bet_type,
            entries=entries,
            fetched_at=datetime.now(UTC),
            source=page.source,
        )
        self.cache.set(cache_key, result, ttl_seconds=30)
        return self._filter_entries(result, combination)

    def _filter_entries(
        self,
        odds: RaceOdds,
        combination: list[str] | None,
        cache_hit: bool = False,
    ) -> RaceOdds:
        if not combination:
            return odds.model_copy(update={"cache_hit": cache_hit})
        filtered = [entry for entry in odds.entries if entry.combination == combination]
        return odds.model_copy(update={"entries": filtered, "cache_hit": cache_hit})

    async def _get_meetings_for_date(self, target_date: date) -> list[MeetingSnapshot]:
        return await self._get_meetings_for_date_from_kind(target_date, kind="card")

    async def _get_meetings_for_date_from_kind(self, target_date: date, kind: str) -> list[MeetingSnapshot]:
        path, select_cname = self._get_selection_endpoint(kind)
        select_page = await self.provider.post_jradb(path, select_cname)
        meetings: list[MeetingSnapshot] = []
        for resolved in self.navigation.list_meetings_from_selection(select_page, target_date, kind=kind):
            cache_key = f"meeting:{target_date.isoformat()}:{resolved.course}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                meetings.append(cached.model_copy(update={"cache_hit": True}))
                continue
            meeting_page = await self.provider.post_jradb(path, resolved.cname)
            meeting = MeetingSnapshot(
                date=target_date,
                course=resolved.course,
                races=parse_meeting_races(meeting_page.content),
                fetched_at=datetime.now(UTC),
                source=meeting_page.source,
            )
            self.cache.set(cache_key, meeting, ttl_seconds=60)
            meetings.append(meeting)
        return meetings

    async def _load_result_race_page(self, target_date: date, course: str, race_no: int):
        meeting_page = await self._load_result_meeting_page(target_date, course)
        race_navigation = parse_result_race_navigation(meeting_page.content)
        race_cname = race_navigation.get(race_no)
        if race_cname is None:
            raise LookupError(f"result race not found for course={course} date={target_date} race_no={race_no}")
        return await self.provider.post_jradb("/JRADB/accessS.html", race_cname)

    async def _load_result_meeting_page(self, target_date: date, course: str):
        cache_key = f"result-meeting-page:{target_date.isoformat()}:{course}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        select_page = await self._load_result_selection_page(target_date)
        resolved = self.navigation.resolve_meeting_from_selection(
            page=select_page,
            target_date=target_date,
            course=course,
            kind="result",
        )
        page = await self.provider.post_jradb("/JRADB/accessS.html", resolved.cname)
        self.cache.set(cache_key, page, ttl_seconds=3600)
        return page

    async def _load_result_selection_page(self, target_date: date):
        cache_key = f"result-selection-page:{target_date.isoformat()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        target_month = f"{target_date.year:04d}-{target_date.month:02d}"
        page = await self.provider.post_jradb("/JRADB/accessS.html", "pw01sli00/AF")
        if self.navigation.list_meetings_from_selection(page, target_date, kind="result"):
            self.cache.set(cache_key, page, ttl_seconds=3600)
            return page
        if not parse_result_month_navigation(page.content):
            page = await self.provider.post_jradb("/JRADB/accessS.html", "pw01skl00999999/B3")
            if self.navigation.list_meetings_from_selection(page, target_date, kind="result"):
                self.cache.set(cache_key, page, ttl_seconds=3600)
                return page

        visited: set[str] = set()
        for _ in range(24):
            month_navigation = parse_result_month_navigation(page.content)
            next_cname = self._select_closest_result_month_cname(month_navigation, target_month, visited)
            if next_cname is None:
                break
            visited.add(next_cname)
            page = await self.provider.post_jradb("/JRADB/accessS.html", next_cname)
            if self.navigation.list_meetings_from_selection(page, target_date, kind="result"):
                self.cache.set(cache_key, page, ttl_seconds=3600)
                return page
        raise LookupError(f"result selection page not found for date={target_date}")

    async def _get_meetings_for_date_from_calendar(self, target_date: date) -> list[MeetingSnapshot]:
        page = await self.provider.fetch_calendar_month(target_date.year, target_date.month)
        parsed = parse_calendar_meetings(page.content, target_date, COURSE_NAMES)
        meetings: list[MeetingSnapshot] = []
        for item in parsed:
            course = item["course"]
            cache_key = f"meeting:{target_date.isoformat()}:{course}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                meetings.append(cached.model_copy(update={"cache_hit": True}))
                continue
            races = [
                race.model_copy(
                    update={"race_id": self._join_race_id(target_date, course, race.race_no)}
                )
                for race in item["races"]
            ]
            meeting = MeetingSnapshot(
                date=target_date,
                course=course,
                races=races,
                fetched_at=datetime.now(UTC),
                source=page.source,
            )
            self.cache.set(cache_key, meeting, ttl_seconds=60)
            meetings.append(meeting)
        return meetings

    async def _get_meetings_for_date_from_result_selection(self, target_date: date) -> list[MeetingSnapshot]:
        try:
            select_page = await self._load_result_selection_page(target_date)
        except LookupError:
            return []

        meetings: list[MeetingSnapshot] = []
        for resolved in self.navigation.list_meetings_from_selection(select_page, target_date, kind="result"):
            cache_key = f"meeting:{target_date.isoformat()}:{resolved.course}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                meetings.append(cached.model_copy(update={"cache_hit": True}))
                continue
            meeting_page = await self.provider.post_jradb("/JRADB/accessS.html", resolved.cname)
            race_navigation = parse_result_race_navigation(meeting_page.content)
            races = [
                MeetingRace(
                    race_no=race_no,
                    race_id=self._join_race_id(target_date, resolved.course, race_no),
                    result_cname=cname,
                )
                for race_no, cname in sorted(race_navigation.items())
            ]
            meeting = MeetingSnapshot(
                date=target_date,
                course=resolved.course,
                races=races,
                fetched_at=datetime.now(UTC),
                source=meeting_page.source,
            )
            self.cache.set(cache_key, meeting, ttl_seconds=3600)
            meetings.append(meeting)
        return meetings

    async def _load_meeting_for_date(self, target_date: date, course: str) -> MeetingSnapshot:
        for kind in ("card", "payout"):
            try:
                path, select_cname = self._get_selection_endpoint(kind)
                select_page = await self.provider.post_jradb(path, select_cname)
                resolved = self.navigation.resolve_meeting_from_selection(
                    page=select_page,
                    target_date=target_date,
                    course=course,
                    kind=kind,
                )
                meeting_page = await self.provider.post_jradb(path, resolved.cname)
                return MeetingSnapshot(
                    date=target_date,
                    course=course,
                    races=parse_meeting_races(meeting_page.content),
                    fetched_at=datetime.now(UTC),
                    source=meeting_page.source,
                )
            except LookupError:
                continue
        for meeting in await self._get_meetings_for_date_from_calendar(target_date):
            if meeting.course == course:
                return meeting
        raise LookupError(f"meeting not found for course={course} date={target_date}")

    @staticmethod
    def _get_selection_endpoint(kind: str) -> tuple[str, str]:
        if kind == "card":
            return "/JRADB/accessD.html", "pw01dli00/F3"
        if kind == "result":
            return "/JRADB/accessS.html", "pw01sli00/AF"
        if kind == "payout":
            return "/JRADB/accessH.html", "pw01hli00/03"
        raise BadRequestError(f"unsupported meeting selection kind={kind}")

    async def _get_jra_race_odds_bundle(
        self,
        race_id: str,
        requested_bet_types: list[str],
        refresh: bool = False,
    ) -> RaceOdds:
        cache_key = f"odds:{race_id}:{','.join(requested_bet_types)}"
        cached = self.cache.get(cache_key)
        if cached is not None and not refresh:
            return cached.model_copy(update={"cache_hit": True})
        target_date, course, race_no = self._split_race_id(race_id)
        meeting = await self.get_meeting(target_date, course)
        race = next((item for item in meeting.races if item.race_no == race_no), None)
        if race is None:
            raise ResourceNotFoundError(f"race not found for race_id={race_id}")
        if race.odds_cname is None:
            raise ResourceNotFoundError(f"odds entry cname not found for race_id={race_id}")
        odds = {}
        source = meeting.source
        for requested_bet_type in requested_bet_types:
            item = await self._get_jra_race_odds(
                race_id=race_id,
                bet_type=requested_bet_type,
                combination=None,
                refresh=refresh,
                initial_cname=race.odds_cname,
            )
            odds[requested_bet_type] = item.entries
            source = item.source
        result = RaceOdds(
            race_id=race_id,
            odds=odds,
            fetched_at=datetime.now(UTC),
            source=source,
        )
        self.cache.set(cache_key, result, ttl_seconds=45)
        return result

    async def _enrich_result_with_card_jockeys(
        self,
        result: RaceResult,
        target_date: date,
        course: str,
        race_no: int,
    ) -> RaceResult:
        if not any(entry.jockey in (None, "") and entry.horse_no for entry in result.results):
            return result
        try:
            card = await self.get_race_card_by_number(target_date, course, race_no)
        except Exception:
            logger.warning(
                "failed to enrich result jockeys from card",
                extra={"race_id": result.race_id, "course": course, "race_no": race_no},
                exc_info=True,
            )
            return result

        jockey_by_horse_no = {
            runner.horse_no: runner.jockey
            for runner in card.runners
            if runner.horse_no not in (None, "") and runner.jockey not in (None, "")
        }
        if not jockey_by_horse_no:
            return result

        return result.model_copy(
            update={
                "results": [
                    entry.model_copy(update={"jockey": jockey_by_horse_no[entry.horse_no]})
                    if entry.horse_no in jockey_by_horse_no and entry.jockey in (None, "")
                    else entry
                    for entry in result.results
                ]
            }
        )

    def _is_fixture_provider(self) -> bool:
        return isinstance(self.provider, FixtureProvider)

    @staticmethod
    def _split_race_id(race_id: str) -> tuple[date, str, int]:
        target_date = date.fromisoformat(f"{race_id[0:4]}-{race_id[4:6]}-{race_id[6:8]}")
        course = COURSE_CODE_TO_NAME[race_id[8:10]]
        race_no = int(race_id[10:12])
        return target_date, course, race_no

    @staticmethod
    def _join_race_id(target_date: date, course: str, race_no: int) -> str:
        course_code = COURSE_NAME_TO_CODE[course]
        return f"{target_date.strftime('%Y%m%d')}{course_code}{race_no:02d}"

    @staticmethod
    def _select_closest_result_month_cname(
        month_navigation: dict[str, str],
        target_month: str,
        visited: set[str],
    ) -> str | None:
        target_index = JraService._month_index(target_month)
        candidates = [
            (abs(JraService._month_index(month) - target_index), JraService._month_index(month), cname)
            for month, cname in month_navigation.items()
            if cname not in visited
        ]
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    @staticmethod
    def _month_index(value: str) -> int:
        year_text, month_text = value.split("-")
        return int(year_text) * 12 + int(month_text)
