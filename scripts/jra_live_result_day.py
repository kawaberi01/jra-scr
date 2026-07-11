from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.service import JraService


async def collect(target_date: date, db_path: Path, output_path: Path, settle_delay_minutes: int) -> dict:
    service = JraService()
    store = AnalysisSQLiteStore(db_path)
    now = datetime.now()
    meetings = await service.get_meetings_for_date(target_date)
    report = {"observed_at": now.astimezone().isoformat(), "saved": [], "not_finalized": [], "evaluated": []}
    for meeting in meetings:
        for race in meeting.races:
            start = _start_datetime(target_date, race.start_time)
            if start is None or (now - start).total_seconds() < settle_delay_minutes * 60:
                continue
            try:
                result = await service.get_race_result_by_number(target_date, meeting.course, race.race_no)
                if not result.results or not result.payouts:
                    report["not_finalized"].append(race.race_id)
                    continue
                store.write_result(result)
                report["saved"].append({"race_id": race.race_id, "results": len(result.results), "payouts": len(result.payouts)})
                for prediction_id in _prediction_ids(db_path, race.race_id):
                    try:
                        evaluation = store.evaluate_prediction_record({"prediction_id": prediction_id})
                        report["evaluated"].append(evaluation)
                    except Exception as exc:
                        report["evaluated"].append({"prediction_id": prediction_id, "error": f"{type(exc).__name__}: {exc}"})
            except Exception as exc:
                report["not_finalized"].append({"race_id": race.race_id, "error": f"{type(exc).__name__}: {exc}"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def _prediction_ids(db_path: Path, race_id: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [row[0] for row in conn.execute("select prediction_id from predictions where race_id = ?", (race_id,))]


def _start_datetime(target_date: date, value: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})時(\d{2})分", value or "")
    return datetime.combine(target_date, datetime.min.time()).replace(hour=int(match.group(1)), minute=int(match.group(2))) if match else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--output", default="data/live/2026-07-11-results.json")
    parser.add_argument("--settle-delay-minutes", type=int, default=10)
    args = parser.parse_args()
    report = asyncio.run(collect(date.fromisoformat(args.date), Path(args.db), Path(args.output), args.settle_delay_minutes))
    print(json.dumps({"saved": len(report["saved"]), "not_finalized": len(report["not_finalized"]), "evaluated": len(report["evaluated"]), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
