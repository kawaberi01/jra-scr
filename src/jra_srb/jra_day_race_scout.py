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
    OddsEntry,
    RaceCard,
    RaceOdds,
    Runner,
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
        mode: str = "quick", time_budget_seconds: float = 45.0,
    ) -> JraDayRaceScoutResult:
        if mode not in {"quick", "deep"}:
            raise ValueError(f"unsupported scout mode={mode}")
        if time_budget_seconds <= 0:
            raise ValueError("time_budget_seconds must be positive")
        observed_at = datetime.now(UTC)
        run_id = f"jra-scout-{target_date:%Y%m%d}-{uuid4().hex[:12]}"
        local_race_ids = self.store.list_pre_race_race_ids(target_date)
        meetings = await self.jra_service.get_meetings_for_date(target_date)
        meeting_race_ids = {
            race.race_id
            for meeting in meetings
            for race in meeting.races
        }
        if local_race_ids and (
            not meeting_race_ids or meeting_race_ids.issubset(local_race_ids)
        ):
            return self._run_from_local_snapshots(
                target_date, run_id, observed_at, local_race_ids, max_candidates,
            )
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
                    async with asyncio.timeout(15):
                        if mode == "quick":
                            card = await self.jra_service.get_race_card_by_number(
                                target_date, meeting.course, race.race_no, refresh=refresh,
                            )
                            materials: list[dict] = []
                            odds = _race_odds_from_card(card)
                            component_status = {
                                "card": "available" if card.runners else "unavailable",
                                "odds": "card_odds" if odds.odds.get("win") else "unavailable",
                                "trend": "not_loaded",
                                "public_analysis": "not_loaded",
                                "best_time_lite": "not_loaded",
                                "closing_speed_lite": "not_loaded",
                                "style_profile_lite": "not_loaded",
                            }
                            race_id = card.race_id
                            race_name = card.race_name
                            start_time = card.start_time or race.start_time
                        else:
                            bundle = await self.prediction_service.get_prediction_bundle(
                                target_date, meeting.course, race.race_no, meeting.meeting_no, meeting.meeting_day,
                                sources=["netkeiba", "keibalab"], odds_bet_types=["win"], refresh=refresh,
                            )
                            materials = build_prediction_record(bundle)["prediction_json"]["predicted_ranking"]
                            card = bundle.card
                            odds = bundle.odds_summary
                            component_status = bundle.meta.component_status
                            race_id = bundle.race_id
                            race_name = bundle.card.race_name
                            start_time = bundle.card.start_time or race.start_time
                records = build_artifact_live_records(
                    artifact, self.analysis_db_path, target_date=target_date, course=meeting.course, card=card,
                )
                history = score_live_records(artifact, records)
                decision = build_win_betting_decision(
                    race_name,
                    history,
                    materials,
                    odds,
                )
                grade, signals, confidence, value = grade_scout_entry(materials, history, decision)
                if mode == "deep":
                    shadow_decision = build_shadow_decision(decision)
                    observations.append(
                        JraLiveShadowObservation(
                            observation_id=f"{run_id}:{race_id}",
                            run_id=run_id,
                            race_id=race_id,
                            race_date=target_date,
                            course=meeting.course,
                            race_no=race.race_no,
                            observed_at=odds.fetched_at,
                            model_version=str(artifact.get("model_version") or "unknown"),
                            model_created_at=artifact.get("created_at"),
                            trained_through=artifact.get("trained_through"),
                            policy_version=shadow_decision.get("policy_version"),
                            decision_status="shadow_only",
                            ticket_status="shadow_only",
                            odds=odds,
                            materials_ranking=materials,
                            history_ranking=history,
                            decision=shadow_decision,
                            component_status=component_status,
                        )
                    )
                return JraDayRaceScoutEntry(
                    race_id=race_id, course=meeting.course, race_no=race.race_no,
                    race_name=race_name, start_time=start_time,
                    grade=grade, signals=signals, confidence_signal=confidence, value_signal=value,
                    reasons=[decision.get("reason", "")], component_status=component_status,
                )
            except Exception as exc:
                errors.append({"race_id": race.race_id, "error_type": type(exc).__name__, "message": str(exc)})
                return self._x_entry(meeting.course, race.race_no, race.race_id, race.race_name,
                                     race.start_time, type(exc).__name__)

        races = [(meeting, race) for meeting in meetings for race in meeting.races]
        tasks = {
            asyncio.create_task(analyze(meeting, race)): (meeting, race)
            for meeting, race in races
        }
        done, pending = await asyncio.wait(tasks, timeout=time_budget_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            errors.append({
                "component": "race_scout",
                "error_type": "time_budget_exceeded",
                "message": f"{len(pending)} races were not analyzed within {time_budget_seconds:g} seconds",
            })
        entries = [task.result() for task in done]
        entries.extend(
            self._x_entry(
                meeting.course, race.race_no, race.race_id, race.race_name,
                race.start_time, "time_budget_exceeded",
            )
            for task, (meeting, race) in tasks.items()
            if task in pending
        )
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

    def _run_from_local_snapshots(
        self,
        target_date: date,
        run_id: str,
        observed_at: datetime,
        race_ids: list[str],
        max_candidates: int,
    ) -> JraDayRaceScoutResult:
        """Score already-collected races without waiting on public web sources."""
        try:
            artifact = load_model_artifact(self.history_model_path)
            if str(artifact.get("trained_through") or "") >= target_date.isoformat():
                raise ValueError("history model training horizon is not before target date")
        except (FileNotFoundError, ValueError) as exc:
            result = JraDayRaceScoutResult(
                run_id=run_id, date=target_date, observed_at=observed_at, status="unavailable",
                race_count=len(race_ids), analyzed_count=0,
                errors=[{"component": "history_model", "error_type": type(exc).__name__, "message": str(exc)}],
            )
            self.store.save_jra_scout_result(result)
            return result

        entries: list[JraDayRaceScoutEntry] = []
        errors: list[dict[str, object]] = []
        for race_id in race_ids:
            try:
                snapshot = self.store.get_pre_race_snapshot(race_id)
                race = snapshot.race
                if _has_started(target_date, race.start_time, observed_at):
                    entries.append(self._x_entry(race.course, race.race_no, race_id, race.race_name,
                                                 race.start_time, "skipped_started"))
                    continue
                card = _race_card_from_snapshot(snapshot)
                odds = _race_odds_from_snapshot(snapshot)
                records = build_artifact_live_records(
                    artifact, self.analysis_db_path, target_date=target_date, course=race.course, card=card,
                )
                history = score_live_records(artifact, records)
                decision = build_win_betting_decision(race.race_name, history, [], odds)
                grade, signals, confidence, value = grade_scout_entry([], history, decision)
                entries.append(JraDayRaceScoutEntry(
                    race_id=race_id, course=race.course, race_no=race.race_no,
                    race_name=race.race_name, start_time=race.start_time, grade=grade,
                    signals=signals, confidence_signal=confidence, value_signal=value,
                    reasons=[decision.get("reason", ""), "ローカルDBの出馬表・単勝オッズで評価（公開指数は未取得）"],
                    component_status={
                        "card": "local_db", "odds": "local_db", "public_analysis": "not_loaded",
                        "best_time_lite": "not_loaded", "closing_speed_lite": "not_loaded",
                        "style_profile_lite": "not_loaded",
                    },
                ))
            except Exception as exc:
                errors.append({"race_id": race_id, "error_type": type(exc).__name__, "message": str(exc)})
                entries.append(self._x_entry("unknown", 0, race_id, None, None, type(exc).__name__))

        sorted_entries = sort_scout_entries(entries)
        candidate_pool = [entry for entry in sorted_entries if entry.grade != "X"]
        candidates = [entry.model_copy(update={"rank": rank}) for rank, entry in enumerate(candidate_pool[:max_candidates], 1)]
        result = JraDayRaceScoutResult(
            run_id=run_id, date=target_date, observed_at=observed_at,
            status="partial" if errors else "completed", race_count=len(race_ids),
            analyzed_count=sum(entry.grade != "X" for entry in entries), candidates=candidates,
            entries=sorted_entries, errors=errors,
        )
        self.store.save_jra_scout_result(result)
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


def _race_card_from_snapshot(snapshot) -> RaceCard:
    race = snapshot.race
    return RaceCard(
        race_id=race.race_id, race_name=race.race_name, course=race.course, distance=race.distance,
        surface=race.surface, surface_label=race.surface_label, start_time=race.start_time,
        weather=race.weather, weather_label=race.weather_label, track_condition=race.track_condition,
        track_condition_label=race.track_condition_label, fetched_at=race.fetched_at or datetime.now(UTC),
        source=f"local_db:{race.source or 'analysis.sqlite'}",
        runners=[
            Runner(
                frame_no=runner.frame_no, horse_no=runner.horse_no, horse_name=runner.horse_name,
                sex_age=runner.sex_age, weight_carried=runner.weight_carried, jockey=runner.jockey,
                trainer=runner.trainer, horse_weight=str(runner.horse_weight) if runner.horse_weight is not None else None,
                horse_weight_diff=str(runner.horse_weight_diff) if runner.horse_weight_diff is not None else None,
                odds=str(runner.card_odds) if runner.card_odds is not None else None,
                popularity=str(runner.card_popularity) if runner.card_popularity is not None else None,
                status=runner.status, status_source=runner.status_source,
            ) for runner in snapshot.runners
        ],
    )


def _race_odds_from_snapshot(snapshot) -> RaceOdds:
    odds = {
        item.bet_type: [
            OddsEntry(
                bet_type=entry.bet_type, combination=entry.combination,
                odds=str(entry.odds) if entry.odds is not None else None,
                odds_min=str(entry.odds_min) if entry.odds_min is not None else None,
                odds_max=str(entry.odds_max) if entry.odds_max is not None else None,
                popularity=str(entry.popularity) if entry.popularity is not None else None,
            ) for entry in item.entries
        ] for item in snapshot.odds
    }
    fetched_at = max((item.fetched_at for item in snapshot.odds), default=snapshot.race.fetched_at or datetime.now(UTC))
    return RaceOdds(race_id=snapshot.race.race_id, odds=odds, fetched_at=fetched_at, source="local_db:analysis.sqlite")


def _race_odds_from_card(card: RaceCard) -> RaceOdds:
    """Create the minimal win-odds view used by a quick scout without another request."""
    entries = [
        OddsEntry(
            bet_type="win",
            combination=[runner.horse_no],
            odds=runner.odds,
            popularity=runner.popularity,
        )
        for runner in card.runners
        if runner.horse_no and runner.odds is not None
    ]
    return RaceOdds(
        race_id=card.race_id,
        odds={"win": entries},
        fetched_at=card.fetched_at,
        source=f"card_odds:{card.source}",
    )
