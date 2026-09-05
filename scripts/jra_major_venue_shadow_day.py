"""Persist pre-race Tokyo/Nakayama v89 shadow predictions and actual odds."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.jra_prediction_service import JraPredictionService
from jra_srb.jra_v_theory import build_v_theory_prediction_record
from jra_srb.service import JraService


TARGET_COURSES = {"tokyo", "nakayama"}
THEORY_VERSION = "v89_autumn_2026_shadow"


def _race_time(target_date: date, value: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})(?:時|:)(\d{2})(?:分)?", value or "")
    if match is None:
        return None
    return datetime.combine(target_date, datetime.min.time()).replace(
        hour=int(match.group(1)), minute=int(match.group(2))
    )


def _already_saved(db_path: Path, race_id: str) -> bool:
    if not db_path.exists():
        return False
    with sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "select 1 from predictions where race_id = ? and theory_version = ? limit 1",
            (race_id, THEORY_VERSION),
        ).fetchone()
    return row is not None


async def run(target_date: date, db_path: Path, min_lead_minutes: int = 10) -> dict:
    jra = JraService()
    prediction_service = JraPredictionService(jra)
    store = AnalysisSQLiteStore(db_path)
    report = {
        "date": target_date.isoformat(),
        "theory_version": THEORY_VERSION,
        "saved": [],
        "skipped": [],
    }
    for meeting in await jra.get_meetings_for_date(target_date):
        if meeting.course not in TARGET_COURSES:
            continue
        if meeting.meeting_no is None or meeting.meeting_day is None:
            report["skipped"].append({"course": meeting.course, "reason": "meeting_metadata_unavailable"})
            continue
        for race in meeting.races:
            start = _race_time(target_date, race.start_time)
            if start is None or (start - datetime.now()).total_seconds() < min_lead_minutes * 60:
                report["skipped"].append({"race_id": race.race_id, "reason": "insufficient_pre_race_lead"})
                continue
            if _already_saved(db_path, race.race_id):
                report["skipped"].append({"race_id": race.race_id, "reason": "shadow_prediction_already_saved"})
                continue
            bundle = await prediction_service.get_prediction_bundle(
                target_date,
                meeting.course,
                race.race_no,
                meeting.meeting_no,
                meeting.meeting_day,
                sources=["netkeiba", "keibalab"],
                odds_bet_types=["win", "wide"],
                refresh=True,
            )
            if (start - datetime.now()).total_seconds() < min_lead_minutes * 60:
                report["skipped"].append({"race_id": race.race_id, "reason": "lead_elapsed_during_fetch"})
                continue
            record = build_v_theory_prediction_record(db_path, bundle)
            if record is None:
                report["skipped"].append({"race_id": race.race_id, "reason": "v89_ranking_unavailable_or_excluded"})
                continue
            store.write_card(target_date, meeting.course, race.race_no, bundle.card)
            if bundle.odds_summary.entries or bundle.odds_summary.odds:
                store.write_odds(bundle.odds_summary, odds_timing="pre_race_shadow")
            saved = store.upsert_prediction_record(record)
            report["saved"].append(
                {
                    "race_id": race.race_id,
                    "prediction_id": record["prediction_id"],
                    "ranking_count": len(record["prediction_json"]["ranking"]),
                    "tickets": len(record["prediction_tickets"]),
                    "ticket_status": record["prediction_json"]["ticket_status"],
                    "saved": saved,
                }
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--min-lead-minutes", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = asyncio.run(run(date.fromisoformat(args.date), Path(args.db), args.min_lead_minutes))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

