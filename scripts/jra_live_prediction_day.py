from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.jra_prediction_engine import build_prediction_record
from jra_srb.jra_prediction_service import JraPredictionService
from jra_srb.service import JraService


MEETING_META = {
    "hakodate": (1, 9),
    "fukushima": (2, 5),
    "kokura": (2, 5),
}


async def predict_day(target_date: date, db_path: Path, output_path: Path, min_lead_minutes: int) -> dict:
    jra = JraService()
    prediction = JraPredictionService(jra)
    store = AnalysisSQLiteStore(db_path)
    now = datetime.now()
    meetings = await jra.get_meetings_for_date(target_date)
    report = {"observed_at": now.astimezone().isoformat(), "date": target_date.isoformat(), "predictions": [], "skipped": []}
    for meeting in meetings:
        meeting_no, meeting_day = MEETING_META[meeting.course]
        for race in meeting.races:
            start = _start_datetime(target_date, race.start_time)
            if start is None or (start - now).total_seconds() < min_lead_minutes * 60:
                report["skipped"].append({"race_id": race.race_id, "reason": "発走済みまたは事前取得猶予不足"})
                continue
            if _has_prediction(db_path, race.race_id):
                report["skipped"].append({"race_id": race.race_id, "reason": "保存済み予想あり"})
                continue
            try:
                bundle = await prediction.get_prediction_bundle(
                    target_date, meeting.course, race.race_no, meeting_no, meeting_day,
                    sources=["netkeiba", "keibalab"], odds_bet_types=["win"], refresh=True,
                )
                record = build_prediction_record(bundle)
                saved = store.upsert_prediction_record(record)
                report["predictions"].append({
                    "race_id": race.race_id,
                    "start_time": race.start_time,
                    "prediction_id": record["prediction_id"],
                    "top3": record["prediction_json"]["predicted_top3"],
                    "component_status": bundle.meta.component_status,
                    "saved": saved,
                })
            except Exception as exc:
                report["skipped"].append({"race_id": race.race_id, "reason": f"{type(exc).__name__}: {exc}"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _start_datetime(target_date: date, value: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})時(\d{2})分", value or "")
    return datetime.combine(target_date, datetime.min.time()).replace(
        hour=int(match.group(1)), minute=int(match.group(2))
    ) if match else None


def _has_prediction(db_path: Path, race_id: str) -> bool:
    if not db_path.exists():
        return False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("select 1 from predictions where race_id = ? limit 1", (race_id,)).fetchone()
    return row is not None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--output", default="data/live/2026-07-11-predictions.json")
    parser.add_argument("--min-lead-minutes", type=int, default=5)
    args = parser.parse_args()
    report = asyncio.run(predict_day(date.fromisoformat(args.date), Path(args.db), Path(args.output), args.min_lead_minutes))
    print(json.dumps({"predictions": len(report["predictions"]), "skipped": len(report["skipped"]), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
