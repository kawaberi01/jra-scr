from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import perf_counter
from uuid import uuid4

from .errors import BadRequestError
from .models import (
    NankankeibaPatternCategoryEntry,
    NankankeibaPatternRate,
    NankanBestTimeRunner,
    NankanClosingSpeedRunner,
    NankanLeadingJockeyItem,
    NankanMeetingTrendContext,
    NankanPredictionBundle,
    NankanPredictionBundleMeta,
    NankanPredictionSummary,
    NankanPredictionSummaryBestTime,
    NankanPredictionSummaryClosingSpeed,
    NankanPredictionSummaryLeadingJockeyItem,
    NankanPredictionSummaryLeadingJockeys,
    NankanPredictionSummaryMeta,
    NankanPredictionSummaryPattern,
    NankanPredictionSummaryRunner,
    NankanPredictionSummaryTrend,
    NankanTrendSummary,
    RaceCard,
)
from .nankankeiba_pattern_service import NankankeibaPatternService
from .nankan_service import NankanService, parse_nankan_odds_summary_bet_types
from .prediction_trace import PredictionTraceLogger, get_current_request_trace_id


@dataclass(frozen=True)
class PredictionBundleContext:
    card: RaceCard
    leading_distance: int | None
    leading_track_condition: str | None


class NankanPredictionService:
    def __init__(
        self,
        nankan_service: NankanService | None = None,
        pattern_service: NankankeibaPatternService | None = None,
        trace_logger: PredictionTraceLogger | None = None,
    ) -> None:
        self.nankan_service = nankan_service or NankanService()
        self.pattern_service = pattern_service or NankankeibaPatternService()
        self.trace_logger = trace_logger or PredictionTraceLogger()

    async def get_prediction_bundle(
        self,
        target_date: date,
        course: str,
        race_no: int,
        meeting_no: int,
        meeting_day: int,
        bet_types: list[str] | None = None,
        refresh: bool = False,
        include_trend_context: bool = True,
    ) -> NankanPredictionBundle:
        bundle_trace_id = uuid4().hex
        request_trace_id = get_current_request_trace_id()
        bundle_started_at = perf_counter()
        summary_bet_types = parse_nankan_odds_summary_bet_types(bet_types)
        self.trace_logger.write(
            "prediction_bundle",
            phase="start",
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            date=target_date.isoformat(),
            course=course,
            race_no=race_no,
            meeting_no=meeting_no,
            meeting_day=meeting_day,
            refresh=refresh,
            bet_types=summary_bet_types,
        )
        race_id = await self.nankan_service._race_id_by_number(target_date, course, race_no, refresh=refresh)
        self.trace_logger.write(
            "prediction_bundle",
            phase="resolved_race",
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
        )
        card = await self._trace_component(
            "card",
            self.nankan_service.get_race_card(race_id, refresh=refresh),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            refresh=refresh,
        )
        bundle_context = self._build_bundle_context(card)

        trend_task = self._trace_component(
            "trend_context",
            self._get_trend_context(
                target_date,
                course,
                race_no,
                refresh=refresh,
                include_trend_context=include_trend_context,
            ),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            refresh=refresh,
            include_trend_context=include_trend_context,
        )
        pattern_task = self._trace_component(
            "pattern",
            self.pattern_service.get_pattern_bundle(
                target_date,
                course,
                meeting_no,
                meeting_day,
                race_no,
                refresh=refresh,
            ),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            refresh=refresh,
        )
        odds_task = self._trace_component(
            "odds_summary",
            self.nankan_service.get_race_odds(
                race_id,
                bet_types=summary_bet_types,
                refresh=refresh,
                card=card,
            ),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            refresh=refresh,
            bet_types=summary_bet_types,
        )
        best_time_task = self._trace_component(
            "best_time",
            self.nankan_service.get_race_best_time(race_id, refresh=refresh, card=card),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            refresh=refresh,
        )
        closing_speed_task = self._trace_component(
            "closing_speed",
            self.nankan_service.get_race_closing_speed(race_id, refresh=refresh, card=card),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            refresh=refresh,
        )
        leading_task = self._trace_component(
            "leading_jockeys",
            self.nankan_service.get_leading_jockeys(
                course=course,
                distance=bundle_context.leading_distance,
                track_condition=bundle_context.leading_track_condition,
                period="recent_3months",
                sort="win_rate",
                refresh=refresh,
            ),
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
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
        bundle = NankanPredictionBundle(
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
            cache_hit=all(getattr(component, "cache_hit", False) for component in components),
            meta=NankanPredictionBundleMeta(parallelized=True, used_existing_services=True),
        )
        self.trace_logger.write(
            "prediction_bundle",
            phase="done",
            bundle_trace_id=bundle_trace_id,
            request_trace_id=request_trace_id,
            race_id=race_id,
            elapsed_ms=round((perf_counter() - bundle_started_at) * 1000, 3),
            cache_hit=bundle.cache_hit,
            components={
                "card": self._component_summary(card),
                "trend_context": self._component_summary(trend_context),
                "pattern": self._component_summary(pattern),
                "odds_summary": self._component_summary(odds_summary),
                "best_time": self._component_summary(best_time),
                "closing_speed": self._component_summary(closing_speed),
                "leading_jockeys": self._component_summary(leading_jockeys),
            },
        )
        return bundle

    async def get_prediction_summary(
        self,
        target_date: date,
        course: str,
        race_no: int,
        meeting_no: int,
        meeting_day: int,
        bet_types: list[str] | None = None,
        refresh: bool = False,
        include_trend_context: bool = True,
    ) -> NankanPredictionSummary:
        bundle = await self.get_prediction_bundle(
            target_date,
            course,
            race_no,
            meeting_no,
            meeting_day,
            bet_types=bet_types,
            refresh=refresh,
            include_trend_context=include_trend_context,
        )
        return self._build_prediction_summary(bundle)

    def _build_bundle_context(self, card: RaceCard) -> PredictionBundleContext:
        return PredictionBundleContext(
            card=card,
            leading_distance=self._safe_leading_distance(card.distance),
            leading_track_condition=self._safe_leading_track_condition(card.track_condition),
        )

    def _build_prediction_summary(self, bundle: NankanPredictionBundle) -> NankanPredictionSummary:
        best_time_by_horse = {runner.horse_no: runner for runner in bundle.best_time.runners}
        closing_speed_by_horse = {runner.horse_no: runner for runner in bundle.closing_speed.runners}
        pattern_by_horse = {runner.horse_no: runner for runner in bundle.pattern.runners}
        win_odds_by_horse = self._win_odds_by_horse(bundle)
        track_condition_key = self._pattern_track_condition_key(bundle.card.track_condition)
        distance_bucket = self._pattern_distance_bucket(bundle.card.distance)

        return NankanPredictionSummary(
            race_id=bundle.race_id,
            date=bundle.date,
            course=bundle.course,
            race_no=bundle.race_no,
            meeting_no=bundle.meeting_no,
            meeting_day=bundle.meeting_day,
            distance=bundle.card.distance,
            track_condition=bundle.card.track_condition,
            track_condition_label=bundle.card.track_condition_label,
            data_status=bundle.card.data_status,
            trend=NankanPredictionSummaryTrend(
                race_count_completed=bundle.trend_context.race_count_completed,
                required_max_completed=bundle.trend_context.required_max_completed,
                usable=bundle.trend_context.usable,
                reason=bundle.trend_context.reason,
                frame_top3=bundle.trend_context.summary.frame[:3],
                jockey_top3=bundle.trend_context.summary.jockey[:3],
                trainer_top3=bundle.trend_context.summary.trainer[:3],
            ),
            leading_jockeys=NankanPredictionSummaryLeadingJockeys(
                course=bundle.leading_jockeys.course,
                distance=bundle.leading_jockeys.distance,
                track_condition=bundle.leading_jockeys.track_condition,
                period=bundle.leading_jockeys.period,
                sort=bundle.leading_jockeys.sort,
                items=[
                    self._build_leading_jockey_summary(item)
                    for item in bundle.leading_jockeys.items[:5]
                ],
            ),
            runners=[
                self._build_prediction_summary_runner(
                    bundle.course,
                    card_runner,
                    best_time_by_horse.get(card_runner.horse_no or ""),
                    closing_speed_by_horse.get(card_runner.horse_no or ""),
                    win_odds_by_horse.get(card_runner.horse_no or ""),
                    getattr(pattern_by_horse.get(card_runner.horse_no or ""), "categories", {}),
                    track_condition_key,
                    distance_bucket,
                )
                for card_runner in bundle.card.runners
            ],
            meta=NankanPredictionSummaryMeta(
                odds_bet_types=list(bundle.odds_bet_types),
                cache_hit=bundle.cache_hit,
            ),
        )

    async def _get_trend_context(
        self,
        target_date: date,
        course: str,
        race_no: int,
        *,
        refresh: bool,
        include_trend_context: bool,
    ) -> NankanMeetingTrendContext:
        if include_trend_context:
            return await self.nankan_service.get_meeting_trend_context(target_date, course, race_no, refresh=refresh)
        return NankanMeetingTrendContext(
            date=target_date,
            course=course,
            race_no=race_no,
            race_count_completed=0,
            required_max_completed=max(race_no - 1, 0),
            usable=False,
            reason="trend context skipped",
            summary=NankanTrendSummary(),
            fetched_at=datetime.now(UTC),
            source="prediction_bundle:skipped",
            trend=None,
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

    def _build_prediction_summary_runner(
        self,
        course: str,
        card_runner,
        best_time: NankanBestTimeRunner | None,
        closing_speed: NankanClosingSpeedRunner | None,
        win_odds_entry,
        categories: dict[str, NankankeibaPatternCategoryEntry],
        track_condition_key: str | None,
        distance_bucket: str | None,
    ) -> NankanPredictionSummaryRunner:
        pattern_uma = categories.get("pattern_uma")
        pattern_kis = categories.get("pattern_kis")
        pattern_kis_cho = categories.get("pattern_kis_cho")
        return NankanPredictionSummaryRunner(
            frame_no=card_runner.frame_no,
            horse_no=card_runner.horse_no,
            horse_name=card_runner.horse_name,
            sex_age=card_runner.sex_age,
            weight_carried=card_runner.weight_carried,
            jockey=card_runner.jockey,
            trainer=card_runner.trainer,
            horse_weight=card_runner.horse_weight,
            horse_weight_diff=card_runner.horse_weight_diff,
            win_odds=card_runner.odds or getattr(win_odds_entry, "odds", None),
            popularity=card_runner.popularity or getattr(win_odds_entry, "popularity", None),
            best_time=self._build_best_time_summary(best_time),
            closing_speed=self._build_closing_speed_summary(closing_speed),
            pattern=NankanPredictionSummaryPattern(
                course_rate=self._pattern_rate(pattern_uma, course),
                distance_rate=self._pattern_rate(pattern_uma, distance_bucket),
                track_condition_rate=self._pattern_track_condition_rate(pattern_uma, track_condition_key),
                jockey_riding_rate=getattr(pattern_kis, "jockey_riding_rate", None),
                jockey_trainer_course_rate=self._pattern_rate(pattern_kis_cho, course),
            ),
        )

    @staticmethod
    def _build_best_time_summary(best_time: NankanBestTimeRunner | None) -> NankanPredictionSummaryBestTime | None:
        if best_time is None:
            return None
        return NankanPredictionSummaryBestTime(
            best_time=best_time.best_time,
            best_time_rank=best_time.best_time_rank,
            same_course_flag=best_time.same_course_flag,
            same_distance_flag=best_time.same_distance_flag,
            track_condition=best_time.track_condition,
        )

    @staticmethod
    def _build_closing_speed_summary(
        closing_speed: NankanClosingSpeedRunner | None,
    ) -> NankanPredictionSummaryClosingSpeed | None:
        if closing_speed is None:
            return None
        return NankanPredictionSummaryClosingSpeed(
            best_closing_time=closing_speed.best_closing_time,
            best_closing_rank=closing_speed.best_closing_rank,
            same_course_flag=closing_speed.same_course_flag,
            same_distance_flag=closing_speed.same_distance_flag,
            track_condition=closing_speed.track_condition,
        )

    @staticmethod
    def _build_leading_jockey_summary(item: NankanLeadingJockeyItem) -> NankanPredictionSummaryLeadingJockeyItem:
        return NankanPredictionSummaryLeadingJockeyItem(
            rank=item.rank,
            jockey_name=item.jockey_name,
            win_rate=item.win_rate,
            quinella_rate=item.quinella_rate,
            trio_rate=item.trio_rate,
        )

    @staticmethod
    def _pattern_rate(
        entry: NankankeibaPatternCategoryEntry | None,
        key: str | None,
    ) -> NankankeibaPatternRate | None:
        if entry is None or key is None:
            return None
        return entry.rates.get(key)

    @staticmethod
    def _pattern_track_condition_rate(
        entry: NankankeibaPatternCategoryEntry | None,
        key: str | None,
    ) -> NankankeibaPatternRate | None:
        if entry is None or key is None:
            return None
        return entry.track_condition_rates.get(key)

    @staticmethod
    def _pattern_track_condition_key(track_condition: str | None) -> str | None:
        if track_condition is None:
            return None
        normalized = track_condition.strip().lower()
        if not normalized:
            return None
        return normalized

    def _pattern_distance_bucket(self, distance: str | None) -> str | None:
        parsed = self.nankan_service._distance_int(distance)
        if parsed is None:
            return None
        if parsed <= 1200:
            return "short"
        if parsed <= 1800:
            return "medium"
        return "long"

    @staticmethod
    def _win_odds_by_horse(bundle: NankanPredictionBundle) -> dict[str, object]:
        win_entries = bundle.odds_summary.odds.get("win", [])
        result: dict[str, object] = {}
        for entry in win_entries:
            if len(entry.combination) != 1:
                continue
            horse_no = entry.combination[0]
            if horse_no:
                result[horse_no] = entry
        return result

    async def _trace_component(self, component: str, awaitable, **fields):
        started_at = perf_counter()
        self.trace_logger.write(component, phase="start", **fields)
        try:
            result = await awaitable
        except Exception as exc:
            self.trace_logger.write(
                component,
                phase="error",
                elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
                error_type=exc.__class__.__name__,
                error=str(exc),
                **fields,
            )
            raise
        self.trace_logger.write(
            component,
            phase="done",
            elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
            summary=self._component_summary(result),
            **fields,
        )
        return result

    @staticmethod
    def _component_summary(result) -> dict:
        summary = {
            "cache_hit": getattr(result, "cache_hit", None),
        }
        meta = getattr(result, "meta", None)
        if meta is not None:
            summary["meta"] = {
                "data_source": getattr(meta, "data_source", None),
                "db_hit": getattr(meta, "db_hit", None),
                "ttl_expired": getattr(meta, "ttl_expired", None),
                "saved": getattr(meta, "saved", None),
                "stale": getattr(meta, "stale", None),
                "refresh_error": getattr(meta, "refresh_error", None),
            }
        if hasattr(result, "runners"):
            summary["runner_count"] = len(getattr(result, "runners"))
        if hasattr(result, "items"):
            summary["item_count"] = len(getattr(result, "items"))
        if hasattr(result, "entries"):
            summary["entry_count"] = len(getattr(result, "entries"))
        if hasattr(result, "odds"):
            odds = getattr(result, "odds")
            summary["odds_counts"] = {key: len(value) for key, value in odds.items()}
        if hasattr(result, "categories"):
            summary["categories"] = list(getattr(result, "categories"))
        if hasattr(result, "usable"):
            summary["usable"] = getattr(result, "usable")
            summary["reason"] = getattr(result, "reason", None)
        return summary
