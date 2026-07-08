from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import logging
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

from .cache import CacheLookupResult, TTLCache
from .errors import BadRequestError, ResourceNotFoundError
from .models import (
    MeetingSnapshot,
    CachePolicyMeta,
    NankanMeetingTrend,
    NankanMeetingTrendContext,
    NankanLeadingJockeyPage,
    NankanRaceBestTime,
    NankanRaceClosingSpeed,
    NankanRaceStyleProfile,
    NankanStyleProfileRunner,
    NankanStyleScores,
    NankanTrendSummary,
    OddsEntry,
    RaceCard,
    RaceCardDataStatus,
    RaceOdds,
    RaceResult,
)
from .nankan_extractors import (
    parse_nankan_calendar_meeting_ids,
    parse_nankan_meeting,
    parse_nankan_meeting_conditions,
    parse_nankan_meeting_trend,
    parse_nankan_best_time,
    parse_nankan_closing_speed,
    parse_nankan_horse_recent_races,
    parse_nankan_leading_jockeys,
    parse_nankan_odds,
    parse_nankan_race_card,
    parse_nankan_race_result,
)
from .nankan_provider import BaseNankanProvider, NANKAN_BET_TYPE_TO_ODDS_CODE, NankanHttpProvider, NankanProviderError

logger = logging.getLogger(__name__)
TModel = TypeVar("TModel", bound=BaseModel)

SUPPORTED_NANKAN_BET_TYPES = set(NANKAN_BET_TYPE_TO_ODDS_CODE)
UNORDERED_NANKAN_BET_TYPES = {"quinella", "wide", "trio"}
NANKAN_COURSE_TO_CODE = {
    "urawa": "18",
    "funabashi": "19",
    "ohi": "20",
    "kawasaki": "21",
}
NANKAN_LEADING_DISTANCES = [
    800,
    900,
    1000,
    1200,
    1300,
    1400,
    1500,
    1600,
    1650,
    1700,
    1800,
    1900,
    2000,
    2100,
    2200,
    2400,
    2600,
]
NANKAN_LEADING_TRACK_CONDITIONS = {
    "good": "01",
    "slightly_heavy": "02",
    "heavy": "03",
    "bad": "04",
}
NANKAN_LEADING_PERIODS = {
    "recent_3months": "0004",
    "recent_1year": "0003",
}
NANKAN_LEADING_SORTS = {
    "wins": "01",
    "earnings": "02",
    "win_rate": "03",
    "quinella_rate": "04",
}
NANKAN_LEADING_COURSES = {
    "urawa": "18",
    "funabashi": "19",
    "ohi": "20",
    "kawasaki": "21",
}
NANKAN_LEADING_DEFAULT_CODE = "000000000000001"


@dataclass(frozen=True)
class NankanCacheTtls:
    odds: int = 60
    trend: int = 300
    card: int = 900
    leading_jockey: int = 21600
    static_material: int = 86400
    result: int = 86400
    meeting: int = 900
    calendar: int = 3600


class NankanService:
    def __init__(
        self,
        provider: BaseNankanProvider | None = None,
        cache: TTLCache | None = None,
        ttl_config: NankanCacheTtls | None = None,
        analysis_store: Any | None = None,
    ) -> None:
        self.provider = provider or NankanHttpProvider()
        self.cache = cache or TTLCache()
        self.ttl_config = ttl_config or NankanCacheTtls()
        self.analysis_store = analysis_store

    async def _get_or_fetch(
        self,
        cache_key: str,
        *,
        ttl_seconds: int,
        refresh: bool,
        fetcher: Callable[[], Awaitable[TModel]],
    ) -> TModel:
        lookup = self._cache_lookup(cache_key)
        if lookup.hit and not lookup.expired and not refresh:
            return self._with_cache_meta(
                lookup.value,
                data_source="db",
                db_hit=True,
                ttl_expired=False,
                saved=False,
                stale=False,
            )
        try:
            fetched = await fetcher()
        except Exception as exc:
            if lookup.hit:
                return self._with_cache_meta(
                    lookup.value,
                    data_source="db",
                    db_hit=True,
                    ttl_expired=lookup.expired,
                    saved=False,
                    stale=True,
                    refresh_error=str(exc),
                )
            raise
        self.cache.set(cache_key, fetched, ttl_seconds=ttl_seconds)
        return self._with_cache_meta(
            fetched,
            data_source="external",
            db_hit=lookup.hit,
            ttl_expired=lookup.expired,
            saved=True,
            stale=False,
        )

    def _cache_lookup(self, cache_key: str) -> CacheLookupResult:
        get_with_status = getattr(self.cache, "get_with_status", None)
        if callable(get_with_status):
            return get_with_status(cache_key, allow_expired=True)
        value = self.cache.get(cache_key)
        return CacheLookupResult(value=value, hit=value is not None)

    @staticmethod
    def _with_cache_meta(
        value: TModel,
        *,
        data_source: str,
        db_hit: bool,
        ttl_expired: bool,
        saved: bool,
        stale: bool,
        refresh_error: str | None = None,
    ) -> TModel:
        fetched_at = NankanService._response_fetched_at(value)
        return value.model_copy(
            update={
                "cache_hit": db_hit,
                "meta": CachePolicyMeta(
                    data_source=data_source,
                    db_hit=db_hit,
                    ttl_expired=ttl_expired,
                    saved=saved,
                    stale=stale,
                    refresh_error=refresh_error,
                    fetched_at=fetched_at,
                ),
            }
        )

    @staticmethod
    def _response_fetched_at(value: BaseModel) -> datetime | None:
        fetched_at = getattr(value, "fetched_at", None)
        if fetched_at is not None:
            return fetched_at
        return getattr(value, "generated_at", None)

    async def get_meeting(self, target_date: date, course: str, refresh: bool = False) -> MeetingSnapshot:
        meeting_id = await self._meeting_id(target_date, course, refresh=refresh)
        cache_key = f"nankan:meeting:{meeting_id}"

        async def fetch() -> MeetingSnapshot:
            page = await self.provider.fetch_meeting(meeting_id)
            parsed = parse_nankan_meeting(page.content, target_date, course)
            return MeetingSnapshot(
                date=target_date,
                course=course,
                races=parsed["races"],
                weather=parsed.get("weather"),
                weather_label=parsed.get("weather_label"),
                track_condition=parsed.get("track_condition"),
                track_condition_label=parsed.get("track_condition_label"),
                surface=parsed.get("surface"),
                surface_label=parsed.get("surface_label"),
                fetched_at=datetime.now(UTC),
                source=page.source,
            )

        return await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.meeting, refresh=refresh, fetcher=fetch)

    async def get_meeting_trend(self, target_date: date, course: str, refresh: bool = False) -> NankanMeetingTrend:
        meeting_id = await self._meeting_id(target_date, course, refresh=refresh)
        trend_meeting_id = self._trend_meeting_id(meeting_id)
        open_date = f"{target_date:%Y%m%d}"
        cache_key = f"nankan:trend:{trend_meeting_id}:{open_date}"
        source = f"https://www.nankankeiba.com/race_trend/{trend_meeting_id}.do?open_date={open_date}"

        async def fetch() -> NankanMeetingTrend:
            try:
                page = await self.provider.fetch_trend(trend_meeting_id, open_date)
            except ResourceNotFoundError:
                return NankanMeetingTrend(
                    date=target_date,
                    course=course,
                    meeting_id=trend_meeting_id,
                    open_date=open_date,
                    race_count_completed=0,
                    summary=NankanTrendSummary(),
                    fetched_at=datetime.now(UTC),
                    source=source,
                )
            parsed = parse_nankan_meeting_trend(page.content)
            return NankanMeetingTrend(
                date=target_date,
                course=course,
                meeting_id=trend_meeting_id,
                open_date=open_date,
                fetched_at=datetime.now(UTC),
                source=page.source,
                **parsed,
            )

        return await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.trend, refresh=refresh, fetcher=fetch)

    async def get_meeting_trend_context(
        self,
        target_date: date,
        course: str,
        race_no: int,
        refresh: bool = False,
    ) -> NankanMeetingTrendContext:
        trend = await self.get_meeting_trend(target_date, course, refresh=refresh)
        required_max_completed = max(race_no - 1, 0)
        usable = trend.race_count_completed <= required_max_completed
        reason = None
        summary = trend.summary
        if not usable:
            reason = "latest trend is post-race snapshot"
            summary = NankanTrendSummary()
        return NankanMeetingTrendContext(
            date=target_date,
            course=course,
            race_no=race_no,
            race_count_completed=trend.race_count_completed,
            required_max_completed=required_max_completed,
            usable=usable,
            reason=reason,
            summary=summary,
            fetched_at=trend.fetched_at,
            source=trend.source,
            trend=trend,
        )

    async def get_race_card(self, race_id: str, refresh: bool = False) -> RaceCard:
        cache_key = f"nankan:card:{race_id}"

        async def fetch() -> RaceCard:
            page = await self.provider.fetch_race_card(race_id)
            parsed = parse_nankan_race_card(page.content)
            if parsed.get("weather") is None or parsed.get("track_condition") is None:
                for key, value in (await self._meeting_conditions_for_race(race_id, refresh=refresh)).items():
                    if parsed.get(key) is None and value is not None:
                        parsed[key] = value
            return RaceCard(race_id=race_id, fetched_at=datetime.now(UTC), source=page.source, **parsed)

        card = await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.card, refresh=refresh, fetcher=fetch)
        return self._ensure_card_data_status(card)

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int, refresh: bool = False) -> RaceCard:
        race_id = await self._race_id_by_number(target_date, course, race_no, refresh=refresh)
        return await self.get_race_card(race_id, refresh=refresh)

    async def get_race_best_time(self, race_id: str, refresh: bool = False) -> NankanRaceBestTime:
        cache_key = f"nankan:best-time:{race_id}"

        async def fetch() -> NankanRaceBestTime:
            card = await self.get_race_card(race_id, refresh=refresh)
            target_distance = self._distance_int(card.distance)
            page = await self.provider.fetch_best(race_id, "000000")
            parsed = parse_nankan_best_time(page.content, target_course=card.course, target_distance=target_distance)
            return NankanRaceBestTime(
                race_id=race_id,
                race_name=card.race_name,
                course=card.course,
                distance=target_distance,
                surface=card.surface,
                runners=parsed["runners"],
                fetched_at=datetime.now(UTC),
                source=page.source,
            )

        return await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.static_material, refresh=refresh, fetcher=fetch)

    async def get_race_best_time_by_number(
        self, target_date: date, course: str, race_no: int, refresh: bool = False
    ) -> NankanRaceBestTime:
        race_id = await self._race_id_by_number(target_date, course, race_no, refresh=refresh)
        return await self.get_race_best_time(race_id, refresh=refresh)

    async def get_race_closing_speed(self, race_id: str, refresh: bool = False) -> NankanRaceClosingSpeed:
        cache_key = f"nankan:closing-speed:{race_id}"

        async def fetch() -> NankanRaceClosingSpeed:
            card = await self.get_race_card(race_id, refresh=refresh)
            target_distance = self._distance_int(card.distance)
            suffix = f"22{target_distance:04d}" if target_distance is not None else "220000"
            page = await self.provider.fetch_best(race_id, suffix)
            parsed = parse_nankan_closing_speed(page.content, target_course=card.course, target_distance=target_distance)
            return NankanRaceClosingSpeed(
                race_id=race_id,
                race_name=card.race_name,
                course=card.course,
                distance=target_distance,
                surface=card.surface,
                runners=parsed["runners"],
                fetched_at=datetime.now(UTC),
                source=page.source,
            )

        return await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.static_material, refresh=refresh, fetcher=fetch)

    async def get_race_closing_speed_by_number(
        self, target_date: date, course: str, race_no: int, refresh: bool = False
    ) -> NankanRaceClosingSpeed:
        race_id = await self._race_id_by_number(target_date, course, race_no, refresh=refresh)
        return await self.get_race_closing_speed(race_id, refresh=refresh)

    async def get_race_style_profile(self, race_id: str, refresh: bool = False) -> NankanRaceStyleProfile:
        cache_key = f"nankan:style-profile:{race_id}"

        async def fetch() -> NankanRaceStyleProfile:
            best_time = await self.get_race_best_time(race_id, refresh=refresh)
            runners: list[NankanStyleProfileRunner] = []
            for runner in best_time.runners:
                recent_races = []
                if runner.horse_profile_id:
                    page = await self.provider.fetch_horse_profile(runner.horse_profile_id)
                    recent_races = parse_nankan_horse_recent_races(page.content)[:5]
                scores = self._style_scores(recent_races)
                runners.append(
                    NankanStyleProfileRunner(
                        horse_no=runner.horse_no,
                        horse_name=runner.horse_name,
                        style_scores=scores,
                        expected_style=self._expected_style(scores, len(recent_races)),
                        sample_size=len(recent_races),
                        recent_races=recent_races,
                        horse_profile_id=runner.horse_profile_id,
                    )
                )
            return NankanRaceStyleProfile(
                race_id=race_id,
                runners=runners,
                fetched_at=datetime.now(UTC),
                source=best_time.source,
            )

        return await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.static_material, refresh=refresh, fetcher=fetch)

    async def get_race_style_profile_by_number(
        self, target_date: date, course: str, race_no: int, refresh: bool = False
    ) -> NankanRaceStyleProfile:
        race_id = await self._race_id_by_number(target_date, course, race_no, refresh=refresh)
        return await self.get_race_style_profile(race_id, refresh=refresh)

    async def get_leading_jockeys(
        self,
        course: str | None = None,
        distance: int | None = None,
        track_condition: str | None = None,
        period: str = "recent_3months",
        sort: str = "win_rate",
        refresh: bool = False,
    ) -> NankanLeadingJockeyPage:
        course_key = self._normalize_leading_course(course)
        distance_value = self._normalize_leading_distance(distance)
        track_key = self._normalize_leading_track_condition(track_condition)
        period_key = self._normalize_leading_period(period)
        sort_key = self._normalize_leading_sort(sort)
        condition_code = self._leading_jockey_condition_code(
            course=course_key,
            distance=distance_value,
            track_condition=track_key,
            period=period_key,
            sort=sort_key,
        )
        cache_key = (
            "nankan:leading:jockeys:"
            f"{course_key or '-'}:{distance_value or '-'}:{track_key or '-'}:{period_key}:{sort_key}:{condition_code}"
        )

        async def fetch() -> NankanLeadingJockeyPage:
            fallback = False
            effective_condition_code = condition_code
            try:
                page = await self.provider.fetch_leading_jockeys(condition_code)
            except (ResourceNotFoundError, NankanProviderError):
                if condition_code == NANKAN_LEADING_DEFAULT_CODE:
                    raise
                fallback = True
                effective_condition_code = NANKAN_LEADING_DEFAULT_CODE
                page = await self.provider.fetch_leading_jockeys(NANKAN_LEADING_DEFAULT_CODE)
            return NankanLeadingJockeyPage(
                source_url=page.source,
                requested_condition_code=condition_code,
                effective_condition_code=effective_condition_code,
                fallback=fallback,
                course=course_key,
                distance=distance_value,
                track_condition=track_key,
                period=period_key,
                sort=sort_key,
                generated_at=datetime.now(UTC),
                items=parse_nankan_leading_jockeys(page.content),
            )

        return await self._get_or_fetch(
            cache_key,
            ttl_seconds=self.ttl_config.leading_jockey,
            refresh=refresh,
            fetcher=fetch,
        )

    async def get_race_result(self, race_id: str, refresh: bool = False) -> RaceResult:
        logger.info("get_nankan_race_result", extra={"race_id": race_id, "refresh": refresh})
        cache_key = f"nankan:result:{race_id}"

        async def fetch() -> RaceResult:
            page = await self.provider.fetch_result(race_id)
            try:
                parsed = parse_nankan_race_result(page.content)
            except LookupError as exc:
                logger.warning(
                    "nankan_result_parse_failed",
                    extra={"race_id": race_id, "source": page.source, "reason": str(exc)},
                )
                raise ResourceNotFoundError(f"nankan result table not found: race_id={race_id}") from exc
            if not parsed["payouts"]:
                logger.warning("nankan_result_payout_table_not_found", extra={"race_id": race_id, "source": page.source})
            return RaceResult(race_id=race_id, fetched_at=datetime.now(UTC), source=page.source, **parsed)

        return await self._get_or_fetch(cache_key, ttl_seconds=self.ttl_config.result, refresh=refresh, fetcher=fetch)

    async def get_race_result_by_number(
        self, target_date: date, course: str, race_no: int, refresh: bool = False
    ) -> RaceResult:
        race_id = await self._race_id_by_number(target_date, course, race_no, refresh=refresh)
        return await self.get_race_result(race_id, refresh=refresh)

    async def get_race_odds(
        self,
        race_id: str,
        bet_type: str | None = None,
        bet_types: list[str] | None = None,
        combination: list[str] | None = None,
        refresh: bool = False,
    ) -> RaceOdds:
        logger.info(
            "get_nankan_race_odds",
            extra={"race_id": race_id, "bet_type": bet_type, "bet_types": bet_types, "refresh": refresh},
        )
        requested = self._requested_bet_types(bet_type, bet_types)
        odds_map = {}
        source = f"nankan:{race_id}"
        any_db_hit = False
        any_ttl_expired = False
        any_saved = False
        any_stale = False
        refresh_errors: list[str] = []
        data_source = "db"
        for current in requested:
            cache_key = f"nankan:odds:{race_id}:{current}"
            lookup = self._cache_lookup(cache_key)
            any_db_hit = any_db_hit or lookup.hit
            any_ttl_expired = any_ttl_expired or lookup.expired
            if lookup.hit and not lookup.expired and not refresh:
                odds_map[current] = await self._complete_win_odds(race_id, lookup.value, refresh=refresh) if current == "win" else lookup.value
                continue
            fetched_success = False
            try:
                page = await self.provider.fetch_odds(race_id, current)
                parsed = parse_nankan_odds(page.content, current)
                entries = parsed.get(current, [])
                source = page.source
                data_source = "external"
                any_saved = True
                fetched_success = True
            except Exception as exc:
                if not lookup.hit:
                    raise
                entries = lookup.value
                any_stale = True
                refresh_errors.append(str(exc))
            if current == "win":
                entries = await self._complete_win_odds(race_id, entries, refresh=refresh)
            if fetched_success:
                self.cache.set(cache_key, entries, ttl_seconds=self.ttl_config.odds)
                self._write_odds_snapshot(
                    RaceOdds(
                        race_id=race_id,
                        odds={current: entries},
                        fetched_at=datetime.now(UTC),
                        source=source,
                    ),
                    bet_type=current,
                )
            odds_map[current] = entries
        result = RaceOdds(race_id=race_id, odds=odds_map, fetched_at=datetime.now(UTC), source=source)
        result = result.model_copy(
            update={
                "cache_hit": any_db_hit and not any_saved,
                "meta": CachePolicyMeta(
                    data_source="db" if any_stale or (any_db_hit and not any_saved) else data_source,
                    db_hit=any_db_hit,
                    ttl_expired=any_ttl_expired,
                    saved=any_saved,
                    stale=any_stale,
                    refresh_error="; ".join(refresh_errors) if refresh_errors else None,
                    fetched_at=result.fetched_at,
                ),
            }
        )
        if bet_type is not None:
            return self._filter_odds(result, bet_type, combination)
        return result

    async def get_race_odds_by_number(
        self,
        target_date: date,
        course: str,
        race_no: int,
        bet_type: str | None = None,
        bet_types: list[str] | None = None,
        combination: list[str] | None = None,
        refresh: bool = False,
    ) -> RaceOdds:
        race_id = await self._race_id_by_number(target_date, course, race_no, refresh=refresh)
        return await self.get_race_odds(
            race_id,
            bet_type=bet_type,
            bet_types=bet_types,
            combination=combination,
            refresh=refresh,
        )

    def _requested_bet_types(self, bet_type: str | None, bet_types: list[str] | None) -> list[str]:
        requested = [bet_type] if bet_type else bet_types
        if requested is None:
            requested = list(SUPPORTED_NANKAN_BET_TYPES)
        for current in requested:
            if current not in SUPPORTED_NANKAN_BET_TYPES:
                raise BadRequestError(f"unsupported nankan bet_type={current}")
        return list(dict.fromkeys(requested))

    async def _race_id_by_number(self, target_date: date, course: str, race_no: int, refresh: bool) -> str:
        meeting = await self.get_meeting(target_date, course, refresh=refresh)
        race = next((item for item in meeting.races if item.race_no == race_no), None)
        if race is None:
            raise LookupError(f"nankan race not found: {target_date.isoformat()} {course} {race_no}R")
        return race.race_id

    async def _complete_win_odds(self, race_id: str, entries: list[OddsEntry], refresh: bool) -> list[OddsEntry]:
        card = await self.get_race_card(race_id, refresh=refresh)
        by_horse_no = {
            entry.combination[0]: entry
            for entry in entries
            if entry.combination and entry.combination[0].isdigit()
        }
        completed: list[OddsEntry] = []
        for runner in card.runners:
            if not runner.horse_no:
                continue
            completed.append(
                by_horse_no.get(
                    runner.horse_no,
                    OddsEntry(bet_type="win", combination=[runner.horse_no], odds=None, popularity=None),
                )
            )
        return sorted(
            completed,
            key=lambda entry: int(entry.combination[0]) if entry.combination and entry.combination[0].isdigit() else 999,
        )

    @staticmethod
    def _filter_odds(odds: RaceOdds, bet_type: str, combination: list[str] | None) -> RaceOdds:
        entries = odds.odds.get(bet_type, [])
        if combination:
            ordered = bet_type not in UNORDERED_NANKAN_BET_TYPES
            normalized = NankanService._normalize_combination(combination, ordered=ordered)
            entries = [
                entry
                for entry in entries
                if NankanService._normalize_combination(entry.combination, ordered=ordered) == normalized
            ]
        return odds.model_copy(update={"bet_type": bet_type, "entries": entries, "odds": {}})

    def _write_odds_snapshot(self, odds: RaceOdds, bet_type: str) -> None:
        if self.analysis_store is None:
            return
        try:
            store = self.analysis_store() if callable(self.analysis_store) else self.analysis_store
            store.write_odds(odds, bet_type=bet_type)
        except Exception as exc:
            logger.warning(
                "nankan_odds_snapshot_write_failed",
                extra={"race_id": odds.race_id, "bet_type": bet_type, "reason": str(exc)},
            )

    @staticmethod
    def _ensure_card_data_status(card: RaceCard) -> RaceCard:
        if card.data_status is not None and card.data_status.horse_weight:
            return card
        if not card.runners:
            status = RaceCardDataStatus(
                horse_weight="unavailable",
                horse_weight_reason="runner table could not be parsed",
            )
        elif any(runner.horse_weight or runner.horse_weight_diff for runner in card.runners):
            status = RaceCardDataStatus(
                horse_weight="available",
                horse_weight_reason="at least one runner has horse_weight or horse_weight_diff",
            )
        else:
            status = RaceCardDataStatus(
                horse_weight="unpublished",
                horse_weight_reason="all runners have null horse_weight before official publication",
            )
        return card.model_copy(update={"data_status": status})

    @staticmethod
    def _normalize_combination(combination: list[str], ordered: bool) -> list[str]:
        normalized = [str(int(item.strip())) if item.strip().isdigit() else item.strip() for item in combination]
        if ordered:
            return normalized
        return sorted(normalized, key=lambda item: int(item) if item.isdigit() else 999)

    @staticmethod
    def _distance_int(value: str | None) -> int | None:
        if not value:
            return None
        digits = "".join(item for item in value if item.isdigit())
        return int(digits) if digits else None

    @staticmethod
    def _style_scores(recent_races: list) -> NankanStyleScores:
        counts = {"front": 0, "stalker": 0, "midpack": 0, "closer": 0}
        for race in recent_races:
            style = NankanService._style_from_recent_race(race)
            if style is not None:
                counts[style] += 1
        total = sum(counts.values())
        if total == 0:
            return NankanStyleScores()
        return NankanStyleScores(**{key: round(value / total, 3) for key, value in counts.items()})

    @staticmethod
    def _style_from_recent_race(race) -> str | None:
        if not race.corner_positions or not race.field_size or race.field_size <= 1:
            return None
        average_position = sum(race.corner_positions) / len(race.corner_positions)
        position_ratio = (average_position - 1) / (race.field_size - 1)
        if position_ratio <= 0.25:
            return "front"
        if position_ratio <= 0.45:
            return "stalker"
        if position_ratio <= 0.70:
            return "midpack"
        return "closer"

    @staticmethod
    def _expected_style(scores: NankanStyleScores, sample_size: int) -> str | None:
        if sample_size == 0:
            return None
        values = scores.model_dump()
        return max(values, key=lambda key: values[key])

    @staticmethod
    def _normalize_leading_course(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in NANKAN_LEADING_COURSES:
            raise BadRequestError(f"unsupported nankan leading course={value}")
        return value

    @staticmethod
    def _normalize_leading_distance(value: int | None) -> int | None:
        if value is None:
            return None
        if value not in NANKAN_LEADING_DISTANCES:
            raise BadRequestError(f"unsupported nankan leading distance={value}")
        return value

    @staticmethod
    def _normalize_leading_track_condition(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in NANKAN_LEADING_TRACK_CONDITIONS:
            raise BadRequestError(f"unsupported nankan leading track_condition={value}")
        return value

    @staticmethod
    def _normalize_leading_period(value: str) -> str:
        if re_year := str(value).strip():
            if re_year.isdigit() and 1998 <= int(re_year) <= 2026:
                return re_year
            if re_year in NANKAN_LEADING_PERIODS:
                return re_year
        raise BadRequestError(f"unsupported nankan leading period={value}")

    @staticmethod
    def _normalize_leading_sort(value: str) -> str:
        if value not in NANKAN_LEADING_SORTS:
            raise BadRequestError(f"unsupported nankan leading sort={value}")
        return value

    @staticmethod
    def _leading_jockey_condition_code(
        course: str | None,
        distance: int | None,
        track_condition: str | None,
        period: str,
        sort: str,
    ) -> str:
        course_code = NANKAN_LEADING_COURSES.get(course or "", "00")
        distance_code = f"{distance:04d}" if distance else "0000"
        track_code = NANKAN_LEADING_TRACK_CONDITIONS.get(track_condition or "", "00")
        if period.isdigit():
            period_code = period
        else:
            period_code = NANKAN_LEADING_PERIODS[period]
        sort_code = NANKAN_LEADING_SORTS[sort]
        return f"{course_code}{distance_code}{track_code}{period_code}{sort_code}1"

    async def _meeting_id(self, target_date: date, course: str, refresh: bool) -> str:
        try:
            course_code = NANKAN_COURSE_TO_CODE[course]
        except KeyError as exc:
            raise LookupError(f"unsupported nankan course={course}") from exc
        cache_key = f"nankan:calendar:{target_date:%Y%m}"
        cached = self._cache_lookup(cache_key)
        if not cached.hit or cached.expired or refresh:
            page = await self.provider.fetch_calendar(target_date.year, target_date.month)
            meeting_ids = parse_nankan_calendar_meeting_ids(page.content)
            self.cache.set(cache_key, meeting_ids, ttl_seconds=self.ttl_config.calendar)
        else:
            meeting_ids = cached.value
        prefix = f"{target_date:%Y%m%d}{course_code}"
        matched = [meeting_id for meeting_id in meeting_ids if meeting_id.startswith(prefix)]
        if not matched:
            raise LookupError(f"nankan meeting not found: {target_date.isoformat()} {course}")
        return matched[0]

    async def _meeting_conditions_for_race(self, race_id: str, refresh: bool) -> dict[str, str | None]:
        meeting_id = race_id[:14]
        cache_key = f"nankan:meeting:conditions:{meeting_id}"
        cached = self._cache_lookup(cache_key)
        if cached.hit and not cached.expired and not refresh:
            return cached.value
        page = await self.provider.fetch_meeting(meeting_id)
        conditions = parse_nankan_meeting_conditions(page.content)
        self.cache.set(cache_key, conditions, ttl_seconds=self.ttl_config.card)
        return conditions

    @staticmethod
    def _trend_meeting_id(meeting_id: str) -> str:
        return f"{meeting_id[:4]}{meeting_id[8:14]}"
