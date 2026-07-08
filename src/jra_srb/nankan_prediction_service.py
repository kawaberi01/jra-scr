from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from .errors import BadRequestError
from .models import NankanPredictionBundle, NankanPredictionBundleMeta
from .nankankeiba_pattern_service import NankankeibaPatternService
from .nankan_service import NankanService, parse_nankan_odds_summary_bet_types


class NankanPredictionService:
    def __init__(
        self,
        nankan_service: NankanService | None = None,
        pattern_service: NankankeibaPatternService | None = None,
    ) -> None:
        self.nankan_service = nankan_service or NankanService()
        self.pattern_service = pattern_service or NankankeibaPatternService()

    async def get_prediction_bundle(
        self,
        target_date: date,
        course: str,
        race_no: int,
        meeting_no: int,
        meeting_day: int,
        bet_types: list[str] | None = None,
        refresh: bool = False,
    ) -> NankanPredictionBundle:
        summary_bet_types = parse_nankan_odds_summary_bet_types(bet_types)
        race_id = await self.nankan_service._race_id_by_number(target_date, course, race_no, refresh=refresh)
        card = await self.nankan_service.get_race_card(race_id, refresh=refresh)

        trend_task = self.nankan_service.get_meeting_trend_context(target_date, course, race_no, refresh=refresh)
        pattern_task = self.pattern_service.get_pattern_bundle(
            target_date,
            course,
            meeting_no,
            meeting_day,
            race_no,
            refresh=refresh,
        )
        odds_task = self.nankan_service.get_race_odds(
            race_id,
            bet_types=summary_bet_types,
            refresh=refresh,
        )
        best_time_task = self.nankan_service.get_race_best_time(race_id, refresh=refresh)
        closing_speed_task = self.nankan_service.get_race_closing_speed(race_id, refresh=refresh)
        leading_task = self.nankan_service.get_leading_jockeys(
            course=course,
            distance=self._safe_leading_distance(card.distance),
            track_condition=self._safe_leading_track_condition(card.track_condition),
            period="recent_3months",
            sort="win_rate",
            refresh=refresh,
        )
        trend_context, pattern, odds_summary, best_time, closing_speed, leading_jockeys = await asyncio.gather(
            trend_task,
            pattern_task,
            odds_task,
            best_time_task,
            closing_speed_task,
            leading_task,
        )

        components = [card, odds_summary, trend_context, best_time, closing_speed, pattern, leading_jockeys]
        return NankanPredictionBundle(
            race_id=race_id,
            date=target_date,
            course=course,
            race_no=race_no,
            meeting_no=meeting_no,
            meeting_day=meeting_day,
            odds_bet_types=summary_bet_types,
            card=card,
            odds_summary=odds_summary,
            trend_context=trend_context,
            best_time=best_time,
            closing_speed=closing_speed,
            pattern=pattern,
            leading_jockeys=leading_jockeys,
            fetched_at=datetime.now(UTC),
            cache_hit=all(component.cache_hit for component in components),
            meta=NankanPredictionBundleMeta(parallelized=True, used_existing_services=True),
        )

    def _safe_leading_distance(self, distance: str | None) -> int | None:
        parsed = self.nankan_service._distance_int(distance)
        if parsed is None:
            return None
        try:
            return self.nankan_service._normalize_leading_distance(parsed)
        except BadRequestError:
            return None

    def _safe_leading_track_condition(self, track_condition: str | None) -> str | None:
        if track_condition is None:
            return None
        try:
            return self.nankan_service._normalize_leading_track_condition(track_condition)
        except BadRequestError:
            return None
