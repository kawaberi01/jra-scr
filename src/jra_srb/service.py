from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Iterable

from .cache import TTLCache
from .config import load_parser_config
from .extractors import (
    parse_meeting_races,
    parse_meeting_payout_result,
    parse_jra_trifecta_odds,
    parse_jra_win_place_odds,
    parse_odds_navigation,
    parse_race_card,
    parse_race_odds,
    parse_race_result,
    parse_race_summaries,
)
from .models import MeetingSnapshot, RaceCard, RaceOdds, RaceResult, RaceSummary
from .navigation import JraNavigation
from .provider import BaseProvider, HttpProvider


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


class JraService:
    def __init__(self, provider: BaseProvider | None = None, cache: TTLCache | None = None) -> None:
        self.provider = provider or HttpProvider()
        self.cache = cache or TTLCache()
        self.navigation = JraNavigation()

    async def get_races(self, target_date: date, course: str | None = None) -> list[RaceSummary]:
        cache_key = f"races:{target_date.isoformat()}:{course or '*'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        page = await self.provider.fetch_races(target_date, course=course)
        races = parse_race_summaries(page.content, load_parser_config("races"))
        self.cache.set(cache_key, races, ttl_seconds=60)
        return races

    async def get_race_card(self, race_id: str) -> RaceCard:
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
        if bet_type is not None:
            return await self._get_jra_race_odds(
                race_id=race_id,
                bet_type=bet_type,
                combination=combination,
                refresh=refresh,
            )
        requested = list(bet_types or [])
        cache_key = f"odds:{race_id}:{','.join(requested) if requested else '*'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
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
        cache_key = f"result-by-number:{target_date.isoformat()}:{course}:{race_no}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        select_page = await self.provider.post_jradb("/JRADB/accessH.html", "pw01hli00/03")
        resolved = self.navigation.resolve_meeting_from_selection(
            page=select_page,
            target_date=target_date,
            course=course,
            kind="payout",
        )
        meeting_page = await self.provider.post_jradb("/JRADB/accessH.html", resolved.cname)
        parsed = parse_meeting_payout_result(meeting_page.content, race_no)
        race_id = self._join_race_id(target_date, course, race_no)
        result = RaceResult(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=meeting_page.source,
            **parsed,
        )
        self.cache.set(cache_key, result, ttl_seconds=3600)
        return result

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        cache_key = f"meeting:{target_date.isoformat()}:{course}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        select_page = await self.provider.post_jradb("/JRADB/accessD.html", "pw01dli00/F3")
        resolved = self.navigation.resolve_meeting_from_selection(
            page=select_page,
            target_date=target_date,
            course=course,
            kind="card",
        )
        meeting_page = await self.provider.post_jradb("/JRADB/accessD.html", resolved.cname)
        meeting = MeetingSnapshot(
            date=target_date,
            course=course,
            races=parse_meeting_races(meeting_page.content),
            fetched_at=datetime.now(UTC),
            source=meeting_page.source,
        )
        self.cache.set(cache_key, meeting, ttl_seconds=60)
        return meeting

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int) -> RaceCard:
        meeting = await self.get_meeting(target_date, course)
        race = next((item for item in meeting.races if item.race_no == race_no), None)
        if race is None or race.card_cname is None:
            raise LookupError(f"race not found: {course} {target_date} {race_no}")
        cache_key = f"card-by-number:{target_date.isoformat()}:{course}:{race_no}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
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
        meeting = await self.get_meeting(target_date, course)
        race = next((item for item in meeting.races if item.race_no == race_no), None)
        if race is None:
            raise LookupError(f"race not found: {course} {target_date} {race_no}")
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
                raise LookupError(f"race not found for race_id={race_id}")
            initial_cname = race.odds_cname
        if initial_cname is None:
            raise LookupError(f"odds entry cname not found for race_id={race_id}")
        root_page = await self.provider.post_jradb("/JRADB/accessO.html", initial_cname)
        navigation = parse_odds_navigation(root_page.content)
        target_cname = navigation.get(bet_type, initial_cname if bet_type == "win" else None)
        if target_cname is None:
            raise LookupError(f"unsupported bet_type={bet_type}")
        page = await self.provider.post_jradb("/JRADB/accessO.html", target_cname)
        if bet_type == "win":
            entries = parse_jra_win_place_odds(page.content)
        elif bet_type == "trifecta":
            entries = parse_jra_trifecta_odds(page.content)
        else:
            raise LookupError(f"unsupported bet_type={bet_type}")
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

    @staticmethod
    def _split_race_id(race_id: str) -> tuple[date, str, int]:
        target_date = date.fromisoformat(f"{race_id[0:4]}-{race_id[4:6]}-{race_id[6:8]}")
        course = COURSE_CODE_TO_NAME[race_id[8:10]]
        race_no = int(race_id[10:12])
        return target_date, course, race_no

    @staticmethod
    def _join_race_id(target_date: date, course: str, race_no: int) -> str:
        course_code = {value: key for key, value in COURSE_CODE_TO_NAME.items()}[course]
        return f"{target_date.strftime('%Y%m%d')}{course_code}{race_no:02d}"
