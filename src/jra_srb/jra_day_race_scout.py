from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from .analysis_store import AnalysisSQLiteStore
from .jra_betting_decision import build_win_betting_decision
from .jra_history_model import build_artifact_live_records, load_model_artifact, score_live_records
from .jra_prediction_engine import build_prediction_record
from .jra_prediction_service import JraPredictionService
from .models import (
    JraDayRaceScoutEntry,
    JraDayRaceScoutResult,
    JraLiveShadowObservation,
    JraScoutConfidenceSignal,
    JraScoutValueSignal,
)
from .service import JraService


def grade_scout_entry(
    materials_ranking: list[dict], history_ranking: list[dict], decision: dict,
) -> tuple[str, list[str], JraScoutConfidenceSignal, JraScoutValueSignal | None]:
    material_top3 = [str(item.get("horse_no") or "") for item in materials_ranking[:3]]
    history_top3 = [str(item.get("horse_no") or "") for item in history_ranking[:3]]
    gap = 0.0
    if len(history_ranking) >= 2:
        gap = float(history_ranking[0].get("win_probability_race_normalized") or 0.0) - float(
            history_ranking[1].get("win_probability_race_normalized") or 0.0
        )
    confidence = JraScoutConfidenceSignal(
        top_pick_agrees=bool(material_top3 and history_top3 and material_top3[0] == history_top3[0]),
        top3_agreement_count=len(set(material_top3) & set(history_top3)),
        history_probability_gap=round(gap, 6),
    )
    has_s = (
        bool(history_ranking)
        and confidence.top_pick_agrees
        and confidence.top3_agreement_count >= 2
        and gap >= 0.05
    )
    has_v = decision.get("status") == "recommended"
    value = None
    if has_v:
        selected = decision.get("selection") or {}
        value = JraScoutValueSignal(
            status="provisional_value",
            horse_no=str(selected.get("horse_no") or "") or None,
            expected_return=float(selected.get("expected_return") or 0.0),
            market_edge=float(selected.get("market_edge") or 0.0),
        )
    signals = (["S"] if has_s else []) + (["V"] if has_v else [])
    return ("A" if has_s and has_v else "B" if has_s or has_v else "C"), signals, confidence, value


def sort_scout_entries(entries: list[JraDayRaceScoutEntry]) -> list[JraDayRaceScoutEntry]:
    grade_order = {"A": 0, "B": 1, "C": 2, "X": 3}
    return sorted(
        entries,
        key=lambda item: (
            grade_order.get(item.grade, 9),
            -(item.value_signal.expected_return if item.value_signal else 0.0),
            -item.confidence_signal.history_probability_gap,
            item.start_time or "99:99",
            item.race_id,
        ),
    )


class JraDayRaceScout:
    def __init__(
        self,
        *,
        jra_service: JraService,
        prediction_service: JraPredictionService,
        store: AnalysisSQLiteStore,
        analysis_db_path: str | Path,
        history_model_path: str | Path,
    ) -> None:
        self.jra_service = jra_service
        self.prediction_service = prediction_service
        self.store = store
        self.analysis_db_path = Path(analysis_db_path)
        self.history_model_path = Path(history_model_path)

    async def run(
        self, target_date: date, *, max_candidates: int = 5,
        refresh: bool = False, max_concurrency: int = 3,
    ) -> JraDayRaceScoutResult:
        observed_at = datetime.now(UTC)
        run_id = f"jra-scout-{target_date:%Y%m%d}-{uuid4().hex[:12]}"
        meetings = await self.jra_service.get_meetings_for_date(target_date)
        race_count = sum(len(meeting.races) for meeting in meetings)
        if not meetings:
            result = JraDayRaceScoutResult(
                run_id=run_id, date=target_date, observed_at=observed_at,
                status="unavailable", race_count=0, analyzed_count=0,
            )
            self.store.save_jra_scout_result(result)
            return result
        try:
            artifact = load_model_artifact(self.history_model_path)
            if str(artifact.get("trained_through") or "") >= target_date.isoformat():
                raise ValueError("history model training horizon is not before target date")
        except (FileNotFoundError, ValueError) as exc:
            entries = [
                self._x_entry(meeting.course, race.race_no, race.race_id, race.race_name, race.start_time,
                              "history_model_unavailable")
                for meeting in meetings for race in meeting.races
            ]
            result = JraDayRaceScoutResult(
                run_id=run_id, date=target_date, observed_at=observed_at, status="unavailable",
                race_count=race_count, analyzed_count=0, entries=entries,
                errors=[{"component": "history_model", "error_type": type(exc).__name__, "message": str(exc)}],
            )
            self.store.save_jra_scout_result(result)
            return result

        semaphore = asyncio.Semaphore(max_concurrency)
        errors: list[dict[str, object]] = []
        observations: list[JraLiveShadowObservation] = []

        async def analyze(meeting, race):
            if meeting.meeting_no is None or meeting.meeting_day is None:
                errors.append({"race_id": race.race_id, "error_type": "meeting_coordinates_unavailable"})
                return self._x_entry(meeting.course, race.race_no, race.race_id, race.race_name,
                                     race.start_time, "meeting_coordinates_unavailable")
            if _has_started(target_date, race.start_time, observed_at):
                return self._x_entry(meeting.course, race.race_no, race.race_id, race.race_name,
                                     race.start_time, "skipped_started")
            try:
                async with semaphore:
                    bundle = await self.prediction_service.get_prediction_bundle(
                        target_date, meeting.course, race.race_no, meeting.meeting_no, meeting.meeting_day,
                        sources=["netkeiba", "keibalab"], odds_bet_types=["win"], refresh=refresh,
                    )
                materials = build_prediction_record(bundle)["prediction_json"]["predicted_ranking"]
                records = build_artifact_live_records(
                    artifact, self.analysis_db_path, target_date=target_date, course=meeting.course, card=bundle.card,
                )
                history = score_live_records(artifact, records)
                decision = build_win_betting_decision(
                    bundle.card.race_name,
                    history,
                    materials,
                    bundle.odds_summary,
                )
                grade, signals, confidence, value = grade_scout_entry(materials, history, decision)
                shadow_decision = build_shadow_decision(decision)
                observations.append(
                    JraLiveShadowObservation(
                        observation_id=f"{run_id}:{bundle.race_id}",
                        run_id=run_id,
                        race_id=bundle.race_id,
                        race_date=target_date,
                        course=meeting.course,
                        race_no=race.race_no,
                        observed_at=bundle.odds_summary.fetched_at,
                        model_version=str(artifact.get("model_version") or "unknown"),
                        model_created_at=artifact.get("created_at"),
                        trained_through=artifact.get("trained_through"),
                        policy_version=shadow_decision.get("policy_version"),
                        decision_status="shadow_only",
                        ticket_status="shadow_only",
                        odds=bundle.odds_summary,
                        materials_ranking=materials,
                        history_ranking=history,
                        decision=shadow_decision,
                        component_status=bundle.meta.component_status,
                    )
                )
                return JraDayRaceScoutEntry(
                    race_id=bundle.race_id, course=meeting.course, race_no=race.race_no,
                    race_name=bundle.card.race_name, start_time=bundle.card.start_time or race.start_time,
                    grade=grade, signals=signals, confidence_signal=confidence, value_signal=value,
                    reasons=[decision.get("reason", "")], component_status=bundle.meta.component_status,
                )
            except Exception as exc:
                errors.append({"race_id": race.race_id, "error_type": type(exc).__name__, "message": str(exc)})
                return self._x_entry(meeting.course, race.race_no, race.race_id, race.race_name,
                                     race.start_time, type(exc).__name__)

        entries = await asyncio.gather(*(analyze(meeting, race) for meeting in meetings for race in meeting.races))
        sorted_entries = sort_scout_entries(entries)
        candidate_pool = [entry for entry in sorted_entries if entry.grade != "X"]
        candidates = [entry.model_copy(update={"rank": rank}) for rank, entry in enumerate(candidate_pool[:max_candidates], 1)]
        analyzed_count = sum(entry.grade != "X" for entry in entries)
        result = JraDayRaceScoutResult(
            run_id=run_id, date=target_date, observed_at=observed_at,
            status="partial" if errors else "completed", race_count=race_count,
            analyzed_count=analyzed_count, candidates=candidates, entries=sorted_entries, errors=errors,
        )
        self.store.save_jra_scout_result(result, observations=observations)
        return result

    @staticmethod
    def _x_entry(course, race_no, race_id, race_name, start_time, reason):
        return JraDayRaceScoutEntry(
            race_id=race_id, course=course, race_no=race_no, race_name=race_name,
            start_time=start_time, grade="X", reasons=[reason],
        )


def _has_started(target_date: date, start_time: str | None, observed_at: datetime) -> bool:
    if not start_time:
        return False
    try:
        hour, minute = (int(value) for value in start_time.replace("時", ":").replace("分", "").split(":")[:2])
    except (TypeError, ValueError):
        return False
    local_now = observed_at.astimezone()
    return target_date < local_now.date() or (
        target_date == local_now.date() and (hour, minute) <= (local_now.hour, local_now.minute)
    )


def build_shadow_decision(decision: dict) -> dict:
    shadow_decision = dict(decision)
    shadow_decision["source_status"] = decision.get("status")
    shadow_decision["status"] = "shadow_only"
    shadow_decision["ticket_status"] = "shadow_only"
    shadow_decision["tickets"] = []
    return shadow_decision
