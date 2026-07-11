from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, date, datetime

from .cache import TTLCache
from .jra_prediction_materials import (
    build_best_time_lite,
    build_closing_speed_lite,
    build_source_keys,
    build_style_profile_lite,
)
from .jra_public_analysis_extractors import (
    parse_keibalab_umabashira,
    parse_netkeiba_data_top,
    parse_umanity_race,
)
from .jra_public_analysis_provider import BaseJraPublicAnalysisProvider, JraPublicAnalysisHttpProvider
from .models import (
    JraMaterialStatus,
    JraPredictionBundle,
    JraPredictionBundleMeta,
    JraPublicAnalysis,
    JraPublicSourceAnalysis,
    JraTrendContext,
    RaceOdds,
)
from .service import JraService


PUBLIC_SOURCES = ("netkeiba", "keibalab", "umanity")


class JraPredictionService:
    def __init__(
        self,
        jra_service: JraService,
        public_provider: BaseJraPublicAnalysisProvider | None = None,
        cache: TTLCache | None = None,
    ) -> None:
        self.jra_service = jra_service
        self.public_provider = public_provider or JraPublicAnalysisHttpProvider()
        self.cache = cache or TTLCache()

    async def get_public_analysis(
        self,
        target_date: date,
        course: str,
        race_no: int,
        meeting_no: int,
        meeting_day: int,
        sources: list[str] | None = None,
        refresh: bool = False,
    ) -> JraPublicAnalysis:
        keys = build_source_keys(target_date, course, race_no, meeting_no, meeting_day)
        requested = list(dict.fromkeys(sources or PUBLIC_SOURCES))
        unsupported = sorted(set(requested) - set(PUBLIC_SOURCES))
        if unsupported:
            raise ValueError(f"unsupported public sources={','.join(unsupported)}")
        items = await asyncio.gather(
            *(self._get_public_source(source, keys, refresh) for source in requested)
        )
        source_map = {item.source: item for item in items}
        for source in PUBLIC_SOURCES:
            source_map.setdefault(
                source,
                JraPublicSourceAnalysis(
                    source=source,
                    status=JraMaterialStatus.disabled,
                    reason="sources指定により取得対象外",
                    fetched_at=datetime.now(UTC),
                ),
            )
        statuses = [source_map[source].status for source in requested]
        available = sum(status == JraMaterialStatus.available for status in statuses)
        status = (
            JraMaterialStatus.available
            if available == len(statuses) and statuses
            else JraMaterialStatus.partial
            if available
            else JraMaterialStatus.unavailable
        )
        return JraPublicAnalysis(
            race_id=keys.jra_internal_race_id,
            date=target_date,
            course=course,
            race_no=race_no,
            meeting_no=meeting_no,
            meeting_day=meeting_day,
            status=status,
            sources=source_map,
            fetched_at=datetime.now(UTC),
            cache_hit=bool(items) and all(item.cache_hit for item in items),
            source_keys=keys,
        )

    async def get_prediction_bundle(
        self,
        target_date: date,
        course: str,
        race_no: int,
        meeting_no: int,
        meeting_day: int,
        sources: list[str] | None = None,
        odds_bet_types: list[str] | None = None,
        refresh: bool = False,
    ) -> JraPredictionBundle:
        bet_types = odds_bet_types or ["win", "wide", "quinella"]
        keys = build_source_keys(target_date, course, race_no, meeting_no, meeting_day)
        card = await self.jra_service.get_race_card_by_number(target_date, course, race_no)
        public, odds, trend = await asyncio.gather(
            self.get_public_analysis(target_date, course, race_no, meeting_no, meeting_day, sources, refresh),
            self._get_odds(keys.jra_internal_race_id, bet_types, refresh),
            self.get_trend_context(target_date, course, race_no),
        )
        best = build_best_time_lite(card, public)
        closing = build_closing_speed_lite(card, public)
        style = build_style_profile_lite(card, public)
        return JraPredictionBundle(
            race_id=keys.jra_internal_race_id,
            date=target_date,
            course=course,
            race_no=race_no,
            meeting_no=meeting_no,
            meeting_day=meeting_day,
            odds_bet_types=bet_types,
            card=card,
            odds_summary=odds,
            trend_context=trend,
            public_analysis=public,
            best_time_lite=best,
            closing_speed_lite=closing,
            style_profile_lite=style,
            fetched_at=datetime.now(UTC),
            cache_hit=card.cache_hit and public.cache_hit and odds.cache_hit,
            meta=JraPredictionBundleMeta(
                source_keys=keys,
                component_status={
                    "card": "available" if card.runners else "unavailable",
                    "odds": "available" if odds.entries or odds.odds else "unavailable",
                    "trend": trend.status.value,
                    "public_analysis": public.status.value,
                    "best_time_lite": best.status.value,
                    "closing_speed_lite": closing.status.value,
                    "style_profile_lite": style.status.value,
                },
            ),
        )

    async def get_lite_material(
        self, kind: str, target_date: date, course: str, race_no: int,
        meeting_no: int, meeting_day: int, refresh: bool = False,
    ):
        card, public = await asyncio.gather(
            self.jra_service.get_race_card_by_number(target_date, course, race_no),
            self.get_public_analysis(
                target_date, course, race_no, meeting_no, meeting_day,
                sources=["keibalab"], refresh=refresh,
            ),
        )
        builders = {
            "best-time-lite": build_best_time_lite,
            "closing-speed-lite": build_closing_speed_lite,
            "style-profile-lite": build_style_profile_lite,
        }
        if kind not in builders:
            raise ValueError(f"unsupported lite material={kind}")
        return builders[kind](card, public)

    async def get_odds_summary(
        self, target_date: date, course: str, race_no: int,
        bet_types: list[str] | None = None, refresh: bool = False,
    ) -> RaceOdds:
        keys = build_source_keys(target_date, course, race_no, 1, 1)
        return await self._get_odds(keys.jra_internal_race_id, bet_types or ["win", "wide", "quinella"], refresh)
    async def get_trend_context(self, target_date: date, course: str, race_no: int) -> JraTrendContext:
        cache_key = f"jra-trend:{target_date}:{course}:{race_no}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        frame_counts: Counter[str] = Counter()
        jockey_counts: Counter[str] = Counter()
        trainer_counts: Counter[str] = Counter()
        skipped: list[int] = []
        completed = 0
        for previous_no in range(1, race_no):
            try:
                result, card = await asyncio.gather(
                    self.jra_service.get_race_result_by_number(target_date, course, previous_no),
                    self.jra_service.get_race_card_by_number(target_date, course, previous_no),
                )
            except Exception:
                skipped.append(previous_no)
                continue
            if not result.results:
                skipped.append(previous_no)
                continue
            completed += 1
            runners = {runner.horse_no: runner for runner in card.runners}
            for entry in result.results[:3]:
                runner = runners.get(entry.horse_no)
                if runner and runner.frame_no:
                    frame_counts[runner.frame_no] += 1
                if entry.jockey or (runner and runner.jockey):
                    jockey_counts[entry.jockey or runner.jockey] += 1
                if runner and runner.trainer:
                    trainer_counts[runner.trainer] += 1
        status = JraMaterialStatus.available if completed == race_no - 1 and completed else JraMaterialStatus.partial if completed else JraMaterialStatus.unavailable
        trend = JraTrendContext(
            date=target_date,
            course=course,
            race_no=race_no,
            race_count_completed=completed,
            required_max_completed=max(race_no - 1, 0),
            usable=completed > 0,
            status=status,
            summary={
                "top3_frames": frame_counts.most_common(),
                "top3_jockeys": jockey_counts.most_common(),
                "top3_trainers": trainer_counts.most_common(),
            },
            skipped_races=skipped,
            reason=None if completed else "同日先行レースの確定結果なし",
            fetched_at=datetime.now(UTC),
        )
        self.cache.set(cache_key, trend, ttl_seconds=60)
        return trend

    async def _get_public_source(self, source, keys, refresh: bool) -> JraPublicSourceAnalysis:
        cache_key = f"jra-public:{source}:{getattr(keys, source + '_race_id', '') or keys.model_dump()}"
        cached = self.cache.get(cache_key)
        if cached is not None and not refresh:
            return cached.model_copy(update={"cache_hit": True})
        try:
            page = await self.public_provider.fetch(source, keys)
            parser = {
                "netkeiba": parse_netkeiba_data_top,
                "keibalab": parse_keibalab_umabashira,
                "umanity": parse_umanity_race,
            }[source]
            result = parser(page.content, page.url)
        except Exception as exc:
            result = JraPublicSourceAnalysis(
                source=source,
                status=JraMaterialStatus.upstream_error,
                reason=f"取得失敗: {type(exc).__name__}",
                fetched_at=datetime.now(UTC),
            )
        self.cache.set(cache_key, result, ttl_seconds=300)
        return result

    async def _get_odds(self, race_id: str, bet_types: list[str], refresh: bool) -> RaceOdds:
        try:
            return await self.jra_service.get_race_odds(race_id, bet_types=bet_types, refresh=refresh)
        except Exception as exc:
            return RaceOdds(
                race_id=race_id,
                fetched_at=datetime.now(UTC),
                source=f"unavailable:{type(exc).__name__}",
            )
