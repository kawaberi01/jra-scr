from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Awaitable, Callable, TypeVar

from pydantic import BaseModel

from .cache import CacheLookupResult, TTLCache
from .models import CachePolicyMeta, NankankeibaPatternBundle, NankankeibaPatternCategoryPage, NankankeibaPatternRunner
from .nankankeiba_pattern_extractors import (
    NANKANKEIBA_PATTERN_CATEGORIES,
    build_pattern_race_id,
    normalize_pattern_category,
    normalize_pattern_course,
    normalize_pattern_period,
    parse_pattern_category_page,
)
from .nankankeiba_pattern_provider import BaseNankankeibaPatternProvider, NankankeibaPatternHttpProvider

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True)
class NankankeibaPatternCacheTtls:
    pattern: int = 86400


class NankankeibaPatternService:
    def __init__(
        self,
        provider: BaseNankankeibaPatternProvider | None = None,
        cache: TTLCache | None = None,
        ttl_config: NankankeibaPatternCacheTtls | None = None,
    ) -> None:
        self.provider = provider or NankankeibaPatternHttpProvider()
        self.cache = cache or TTLCache()
        self.ttl_config = ttl_config or NankankeibaPatternCacheTtls()

    async def _get_or_fetch(
        self,
        cache_key: str,
        *,
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
        self.cache.set(cache_key, fetched, ttl_seconds=self.ttl_config.pattern)
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
                    fetched_at=getattr(value, "fetched_at", None),
                ),
            }
        )

    async def get_pattern_category(
        self,
        target_date: date,
        course: str,
        meeting_no: int,
        meeting_day: int,
        race_no: int,
        category: str,
        period: str = "lifetime",
        refresh: bool = False,
    ) -> NankankeibaPatternCategoryPage:
        course_key = normalize_pattern_course(course)
        period_code = normalize_pattern_period(period)
        category_key = normalize_pattern_category(category)
        race_id = build_pattern_race_id(target_date, course_key, meeting_no, meeting_day, race_no, period_code)
        cache_key = f"nankankeiba:pattern:{race_id}:{category_key}"

        async def fetch() -> NankankeibaPatternCategoryPage:
            page = await self.provider.fetch_pattern(race_id, category_key)
            return NankankeibaPatternCategoryPage(
                race_id=race_id,
                category=category_key,
                entries=parse_pattern_category_page(page.content, race_id, category_key),
                fetched_at=datetime.now(UTC),
                source=page.source,
            )

        return await self._get_or_fetch(cache_key, refresh=refresh, fetcher=fetch)

    async def get_pattern_bundle(
        self,
        target_date: date,
        course: str,
        meeting_no: int,
        meeting_day: int,
        race_no: int,
        periods: list[str] | None = None,
        categories: list[str] | None = None,
        refresh: bool = False,
    ) -> NankankeibaPatternBundle:
        course_key = normalize_pattern_course(course)
        period_codes = [normalize_pattern_period(period) for period in (periods or ["lifetime"])]
        category_keys = [normalize_pattern_category(category) for category in (categories or list(NANKANKEIBA_PATTERN_CATEGORIES))]
        if len(period_codes) != 1:
            raise LookupError("only one nankankeiba pattern period is supported")
        period_code = period_codes[0]
        race_id = build_pattern_race_id(target_date, course_key, meeting_no, meeting_day, race_no, period_code)
        cache_key = f"nankankeiba:pattern:bundle:{race_id}:{','.join(category_keys)}"

        async def fetch() -> NankankeibaPatternBundle:
            pages = await asyncio.gather(
                *[
                    self.get_pattern_category(
                        target_date,
                        course_key,
                        meeting_no,
                        meeting_day,
                        race_no,
                        category,
                        period_code,
                        refresh=refresh,
                    )
                    for category in category_keys
                ]
            )
            runners = _merge_category_pages(list(pages))
            return NankankeibaPatternBundle(
                race_id=race_id,
                date=target_date,
                course=course_key,
                meeting_no=meeting_no,
                meeting_day=meeting_day,
                race_no=race_no,
                periods=period_codes,
                categories=category_keys,
                runners=runners,
                fetched_at=datetime.now(UTC),
                source=";".join(page.source for page in pages),
            )

        return await self._get_or_fetch(cache_key, refresh=refresh, fetcher=fetch)


def _merge_category_pages(pages: list[NankankeibaPatternCategoryPage]) -> list[NankankeibaPatternRunner]:
    merged: dict[str, NankankeibaPatternRunner] = {}
    for page in pages:
        for entry in page.entries:
            runner = merged.get(entry.horse_no)
            if runner is None:
                runner = NankankeibaPatternRunner(
                    frame_no=entry.frame_no,
                    horse_no=entry.horse_no,
                    horse_name=entry.horse_name,
                    jockey=entry.jockey,
                    weight_carried=entry.weight_carried,
                    trainer=entry.trainer,
                )
                merged[entry.horse_no] = runner
            runner.categories[page.category] = entry
    return [merged[key] for key in sorted(merged, key=_runner_sort_key)]


def _runner_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)
