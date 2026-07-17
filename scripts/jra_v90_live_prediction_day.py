"""Save pre-race v90_summer predictions without reading target-race results."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.jra_prediction_service import JraPredictionService
from jra_srb.service import JraService


SUMMER_COURSES = {"sapporo": "01", "hakodate": "02", "fukushima": "03", "niigata": "04", "kokura": "10"}
MEETING_META = {"hakodate": (1, 9), "fukushima": (2, 5), "kokura": (2, 5)}


def _evaluator():
    path = Path(__file__).parents[1] / ".workstate" / "jra-srb" / "prediction-v1-validation" / "evaluate_v1_validation.py"
    spec = importlib.util.spec_from_file_location("v90_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load v90 evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _float(value: object) -> float | None:
    try:
        return float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _race_time(target_date: date, value: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})時(\d{2})分", value or "")
    return datetime.combine(target_date, datetime.min.time()).replace(hour=int(match.group(1)), minute=int(match.group(2))) if match else None


def build_record(bundle, rows: dict, evaluator) -> dict | None:
    theory = evaluator.THEORIES["v90"]
    course_code = SUMMER_COURSES.get(bundle.course)
    if course_code is None:
        return None
    history = evaluator.build_history(rows, bundle.date.isoformat())
    card = bundle.card
    field_size = len(card.runners)
    surface = "dirt" if "ダート" in (card.surface or card.course or "") else "turf"
    distance = int(card.distance) if str(card.distance or "").isdigit() else None
    candidates = []
    for runner in card.runners:
        odds = _float(runner.odds)
        popularity = evaluator.int_or_none(runner.popularity)
        weight_diff = evaluator.int_or_none(str(runner.horse_weight_diff or "").replace("+", ""))
        row = {"horse_name": runner.horse_name, "jockey": runner.jockey, "trainer": runner.trainer,
               "surface": surface, "course": bundle.course, "distance": distance, "race_no": bundle.race_no,
               "field_size": field_size}
        hist = history.horses[runner.horse_name]
        if len(hist) < theory.min_history:
            continue
        nk = SimpleNamespace(horse_no=runner.horse_no, horse_name=runner.horse_name, win_odds=odds,
                             popularity=popularity, horse_weight_diff=weight_diff)
        features = evaluator.hist_features(hist, row, history)
        candidates.append({"row": row, "nk": nk, "features": features, "score": evaluator.score(features, theory, nk=nk)})
    if len(candidates) < theory.min_candidates or field_size < (theory.min_field_size_to_bet or 0) or bundle.race_no > (theory.max_race_no_to_bet or 99):
        return None
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    for item in ranked:
        item["axis_score"] = item["score"] + evaluator.axis_context_score_adjustment(item["features"], theory)
    axis = next((item for item in sorted(ranked, key=lambda item: item["axis_score"], reverse=True)
                 if item["nk"].win_odds is not None and item["nk"].win_odds <= theory.axis_odds_max
                 and (item["nk"].popularity is None or item["nk"].popularity <= theory.axis_popularity_max)), None)
    if axis is None:
        return None
    middles = []
    for item in ranked:
        if item is axis or item["nk"].win_odds is None:
            continue
        odds = item["nk"].win_odds
        if not (theory.middle_odds_min <= odds <= theory.middle_odds_max):
            continue
        if not evaluator.middle_context_allowed(item["features"], theory, odds):
            continue
        item["middle_score"] = item["score"] + evaluator.middle_context_score_adjustment(item["features"], theory, odds, axis["nk"].win_odds)
        middles.append(item)
    middles.sort(key=lambda item: item["middle_score"], reverse=True)
    selected = []
    axis_bucket = str(axis["nk"].popularity or "missing")
    axis_odds_bucket = evaluator.axis_odds_bucket(axis["nk"].win_odds)
    for middle in middles:
        ratio = middle["nk"].win_odds / axis["nk"].win_odds
        ratio_bucket = "lt_2" if ratio < 2 else "2_3_5" if ratio < 3.5 else "3_5_5" if ratio < 5 else "ge_5"
        if evaluator.ticket_middle_allowed(middle, theory, axis_bucket, axis_odds_bucket, ratio_bucket):
            selected.append(middle)
        if len(selected) >= (theory.standard_max_middles or theory.max_middles):
            break
    if not selected:
        return None
    now = datetime.now().astimezone().isoformat()
    tickets = [{"ticket_id": f"v90-{bundle.race_id}-wide-{index}", "bucket": "main", "bet_type": "wide",
                "selection": f"{axis['nk'].horse_no}-{middle['nk'].horse_no}",
                "selection_json": [axis["nk"].horse_no, middle["nk"].horse_no], "amount": 100,
                "reason": "v90_summer pre-race rule"} for index, middle in enumerate(selected, 1)]
    ranking = [{"horse_no": item["nk"].horse_no, "horse_name": item["nk"].horse_name,
                "score": round(item["score"], 3), "win_odds": item["nk"].win_odds} for item in ranked]
    return {"prediction_id": f"v90-{bundle.race_id}-{now.replace(':', '').replace('+', '-')}", "race_id": bundle.race_id,
            "theory_version": "v90_summer", "mode": "paper_validation", "budget": len(tickets) * 100, "created_at": now,
            "pre_race_snapshot": bundle.model_dump(mode="json"), "prediction_json": {"predicted_ranking": ranking,
            "axis_horse_numbers": [axis["nk"].horse_no], "generated_before_result": True}, "prediction_tickets": tickets}


async def run(target_date: date, db_path: Path, min_lead_minutes: int) -> dict:
    evaluator = _evaluator()
    rows = evaluator.load_rows(db_path)
    service, prediction, store = JraService(), None, AnalysisSQLiteStore(db_path)
    prediction = JraPredictionService(service)
    report = {"date": target_date.isoformat(), "saved": [], "skipped": []}
    for meeting in await service.get_meetings_for_date(target_date):
        if meeting.course not in SUMMER_COURSES or meeting.course not in MEETING_META:
            continue
        meeting_no, meeting_day = MEETING_META[meeting.course]
        for race in meeting.races:
            start = _race_time(target_date, race.start_time)
            if start is None or (start - datetime.now()).total_seconds() < min_lead_minutes * 60:
                continue
            bundle = await prediction.get_prediction_bundle(target_date, meeting.course, race.race_no, meeting_no, meeting_day, sources=["netkeiba", "keibalab"], odds_bet_types=["win", "wide"], refresh=True)
            record = build_record(bundle, rows, evaluator)
            if record is None:
                report["skipped"].append({"race_id": race.race_id, "reason": "v90_no_ticket"})
            else:
                store.upsert_prediction_record(record)
                report["saved"].append({"race_id": race.race_id, "prediction_id": record["prediction_id"], "tickets": record["prediction_tickets"]})
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--min-lead-minutes", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(date.fromisoformat(args.date), Path(args.db), args.min_lead_minutes)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
