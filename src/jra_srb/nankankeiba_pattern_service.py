from __future__ import annotations

from datetime import UTC, date, datetime

from .cache import TTLCache
from .models import NankankeibaPatternBundle, NankankeibaPatternCategoryPage, NankankeibaPatternRunner
from .nankankeiba_pattern_extractors import (
    NANKANKEIBA_PATTERN_CATEGORIES,
    build_pattern_race_id,
    normalize_pattern_category,
    normalize_pattern_course,
    normalize_pattern_period,
    parse_pattern_category_page,
)
from .nankankeiba_pattern_provider import BaseNankankeibaPatternProvider, NankankeibaPatternHttpProvider


class NankankeibaPatternService:
    def __init__(self, provider: BaseNankankeibaPatternProvider | None = None, cache: TTLCache | None = None) -> None:
        self.provider = provider or NankankeibaPatternHttpProvider()
        self.cache = cache or TTLCache()

    async def get_pattern_category(
        self,
        target_date: date,
        course: str,
        meeting_no: int,
        meeting_day: int,
        race_no: int,
        category: str,
        period: str = "lifetime",
    ) -> NankankeibaPatternCategoryPage:
        course_key = normalize_pattern_course(course)
        period_code = normalize_pattern_period(period)
        category_key = normalize_pattern_category(category)
        race_id = build_pattern_race_id(target_date, course_key, meeting_no, meeting_day, race_no, period_code)
        cache_key = f"nankankeiba:pattern:{race_id}:{category_key}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_pattern(race_id, category_key)
        result = NankankeibaPatternCategoryPage(
            race_id=race_id,
            category=category_key,
            entries=parse_pattern_category_page(page.content, race_id, category_key),
            fetched_at=datetime.now(UTC),
            source=page.source,
        )
        self.cache.set(cache_key, result, ttl_seconds=300)
        return result

    async def get_pattern_bundle(
        self,
        target_date: date,
        course: str,
        meeting_no: int,
        meeting_day: int,
        race_no: int,
        periods: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> NankankeibaPatternBundle:
        course_key = normalize_pattern_course(course)
        period_codes = [normalize_pattern_period(period) for period in (periods or ["lifetime"])]
        category_keys = [normalize_pattern_category(category) for category in (categories or list(NANKANKEIBA_PATTERN_CATEGORIES))]
        if len(period_codes) != 1:
            raise LookupError("only one nankankeiba pattern period is supported")
        period_code = period_codes[0]
        race_id = build_pattern_race_id(target_date, course_key, meeting_no, meeting_day, race_no, period_code)
        cache_key = f"nankankeiba:pattern:bundle:{race_id}:{','.join(category_keys)}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})

        pages = [
            await self.get_pattern_category(
                target_date,
                course_key,
                meeting_no,
                meeting_day,
                race_no,
                category,
                period_code,
            )
            for category in category_keys
        ]
        runners = _merge_category_pages(pages)
        result = NankankeibaPatternBundle(
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
        self.cache.set(cache_key, result, ttl_seconds=300)
        return result


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
