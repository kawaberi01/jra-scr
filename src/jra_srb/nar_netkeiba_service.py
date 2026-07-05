from __future__ import annotations

from datetime import UTC, date, datetime
import logging

from .cache import TTLCache
from .errors import BadRequestError
from .models import MeetingSnapshot, NarCalendarPage, NetkeibaRaceResult, RaceCard, RaceOdds
from .nar_netkeiba_extractors import (
    NAR_BET_TYPE_TO_ODDS_TYPE,
    normalize_nar_course_key,
    parse_nar_calendar,
    parse_nar_meeting,
    parse_nar_odds,
    parse_nar_race_card,
    parse_nar_race_result,
)
from .nar_netkeiba_provider import BaseNarNetkeibaProvider, NarNetkeibaHttpProvider

logger = logging.getLogger(__name__)


SUPPORTED_NAR_NETKEIBA_BET_TYPES = set(NAR_BET_TYPE_TO_ODDS_TYPE)
UNORDERED_NAR_NETKEIBA_BET_TYPES = {"bracket_quinella", "quinella", "wide", "trio"}


class NarNetkeibaService:
    def __init__(self, provider: BaseNarNetkeibaProvider | None = None, cache: TTLCache | None = None) -> None:
        self.provider = provider or NarNetkeibaHttpProvider()
        self.cache = cache or TTLCache()

    async def get_calendar(self, year: int, month: int, course: str | None = None) -> NarCalendarPage:
        course_key = normalize_nar_course_key(course) if course else None
        cache_key = f"nar:calendar:{year:04d}{month:02d}:{course_key or 'all'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        jyo_cd = _course_key_to_jyo_cd(course_key) if course_key else None
        page = await self.provider.fetch_calendar(year, month, jyo_cd=jyo_cd)
        entries = parse_nar_calendar(page.content)
        if course_key:
            entries = [entry for entry in entries if entry.course_key == course_key]
        result = NarCalendarPage(
            year=year,
            month=month,
            course=course_key,
            entries=entries,
            fetched_at=datetime.now(UTC),
            source=page.source,
        )
        self.cache.set(cache_key, result, ttl_seconds=3600)
        return result

    async def get_meeting(self, date_: date, course: str) -> MeetingSnapshot:
        course_key = normalize_nar_course_key(course)
        calendar = await self.get_calendar(date_.year, date_.month, course_key)
        target = next((entry for entry in calendar.entries if entry.date == date_), None)
        if target is None:
            raise LookupError(f"nar meeting not found: {date_.isoformat()} {course}")
        cache_key = f"nar:meeting:{target.kaisai_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_race_list(date_.strftime("%Y%m%d"), target.kaisai_id)
        parsed = parse_nar_meeting(page.content, target.kaisai_id)
        result = MeetingSnapshot(
            date=date_,
            course=parsed["course"] or target.course,
            races=parsed["races"],
            fetched_at=datetime.now(UTC),
            source=page.source,
        )
        self.cache.set(cache_key, result, ttl_seconds=900)
        return result

    async def get_race_card(self, race_id: str) -> RaceCard:
        cache_key = f"nar:card:{race_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_race_card(race_id)
        parsed = parse_nar_race_card(page.content)
        result = RaceCard(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        self.cache.set(cache_key, result, ttl_seconds=300)
        return result

    async def get_race_result(self, race_id: str) -> NetkeibaRaceResult:
        cache_key = f"nar:result:{race_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_race_result(race_id)
        parsed = parse_nar_race_result(page.content)
        result = NetkeibaRaceResult(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        self.cache.set(cache_key, result, ttl_seconds=3600)
        return result

    async def get_race_odds(
        self,
        race_id: str,
        bet_type: str | None = None,
        combination: list[str] | None = None,
        refresh: bool = False,
    ) -> RaceOdds:
        if bet_type is not None and bet_type not in SUPPORTED_NAR_NETKEIBA_BET_TYPES:
            raise BadRequestError(f"unsupported nar netkeiba bet_type={bet_type}")
        if bet_type:
            odds_map = await self._fetch_odds_map_for_bet_type(race_id, bet_type, refresh=refresh)
        else:
            odds_map = {}
            for current in NAR_BET_TYPE_TO_ODDS_TYPE:
                odds_map.update(await self._fetch_odds_map_for_bet_type(race_id, current, refresh=refresh))
        result = RaceOdds(
            race_id=race_id,
            odds=odds_map,
            fetched_at=datetime.now(UTC),
            source=f"nar-netkeiba:{race_id}",
        )
        return self._filter_odds(result, bet_type, combination)

    async def _fetch_odds_map_for_bet_type(self, race_id: str, bet_type: str, refresh: bool) -> dict[str, list]:
        odds_type = NAR_BET_TYPE_TO_ODDS_TYPE[bet_type]
        cache_key = f"nar:odds:{race_id}:{odds_type}"
        cached = self.cache.get(cache_key)
        if cached is not None and not refresh:
            return cached
        page = await self.provider.fetch_odds(race_id, odds_type)
        parsed = parse_nar_odds(page.content)
        self.cache.set(cache_key, parsed, ttl_seconds=300)
        return parsed

    @staticmethod
    def _filter_odds(odds: RaceOdds, bet_type: str | None, combination: list[str] | None) -> RaceOdds:
        if bet_type is None:
            return odds
        entries = odds.odds.get(bet_type, [])
        if combination:
            ordered = bet_type not in UNORDERED_NAR_NETKEIBA_BET_TYPES
            normalized = NarNetkeibaService._normalize_combination(combination, ordered=ordered)
            entries = [
                entry
                for entry in entries
                if NarNetkeibaService._normalize_combination(entry.combination, ordered=ordered) == normalized
            ]
        return odds.model_copy(update={"bet_type": bet_type, "entries": entries, "odds": {}})

    @staticmethod
    def _normalize_combination(combination: list[str], ordered: bool) -> list[str]:
        normalized = []
        for item in combination:
            value = item.strip()
            normalized.append(str(int(value)) if value.isdigit() else value)
        if ordered:
            return normalized
        return sorted(normalized, key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


def _course_key_to_jyo_cd(course_key: str) -> str:
    mapping = {
        "monbetsu": "30",
        "morioka": "35",
        "mizusawa": "36",
        "urawa": "42",
        "funabashi": "43",
        "oi": "44",
        "kawasaki": "45",
        "kanazawa": "46",
        "kasamatsu": "47",
        "nagoya": "48",
        "sonoda": "50",
        "himeji": "51",
        "kochi": "54",
        "saga": "55",
        "obihiro": "65",
    }
    try:
        return mapping[course_key]
    except KeyError as exc:
        raise LookupError(f"nar course not supported for calendar lookup: {course_key}") from exc
