from __future__ import annotations

import asyncio
from datetime import date, datetime, time
import json
from pathlib import Path
import re
import sqlite3

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.service import JraService


TARGET_DATE = date(2026, 7, 11)
END_AT = datetime.combine(TARGET_DATE, time(16, 50))
DB_PATH = Path("data/db/analysis.sqlite")
SNAPSHOT_DIR = Path("data/live/snapshots")
EVENT_LOG = Path("data/live/2026-07-11-monitor.jsonl")


async def main() -> None:
    service = JraService()
    store = AnalysisSQLiteStore(DB_PATH)
    meetings = await service.get_meetings_for_date(TARGET_DATE)
    captured: set[str] = {
        path.name.split("-", 1)[0]
        for path in SNAPSHOT_DIR.glob("20260711*.json")
    } if SNAPSHOT_DIR.exists() else set()
    while datetime.now() <= END_AT:
        now = datetime.now()
        for meeting in meetings:
            for race in meeting.races:
                start = _start_datetime(race.start_time)
                if start is None:
                    continue
                seconds_to_start = (start - now).total_seconds()
                if race.race_id not in captured and 0 < seconds_to_start <= 10 * 60:
                    await _capture_pre_race(service, store, meeting.course, race.race_no, race.race_id, now)
                    captured.add(race.race_id)
                if (now - start).total_seconds() >= 8 * 60 and not store.has_result(race.race_id):
                    await _capture_result(service, store, meeting.course, race.race_no, race.race_id, now)
        await asyncio.sleep(60)
    _event({"at": datetime.now().astimezone().isoformat(), "event": "monitor_finished"})


async def _capture_pre_race(service, store, course, race_no, race_id, now):
    try:
        card, odds = await asyncio.gather(
            service.get_race_card_by_number(TARGET_DATE, course, race_no),
            service.get_race_odds(race_id, bet_types=["win"], refresh=True),
        )
        payload = {
            "race_id": race_id,
            "captured_at": now.astimezone().isoformat(),
            "state": "pre_race",
            "card": card.model_dump(mode="json"),
            "odds": odds.model_dump(mode="json"),
        }
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{race_id}-{now:%H%M%S}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _event({"at": payload["captured_at"], "event": "pre_race_snapshot", "race_id": race_id})
    except Exception as exc:
        _event({"at": now.astimezone().isoformat(), "event": "pre_race_error", "race_id": race_id, "error": f"{type(exc).__name__}: {exc}"})


async def _capture_result(service, store, course, race_no, race_id, now):
    try:
        result = await service.get_race_result_by_number(TARGET_DATE, course, race_no)
        if not result.results or not result.payouts:
            return
        store.write_result(result)
        evaluations = []
        for prediction_id in _prediction_ids(race_id):
            evaluations.append(store.evaluate_prediction_record({"prediction_id": prediction_id}))
        _event({
            "at": now.astimezone().isoformat(), "event": "result_saved", "race_id": race_id,
            "results": len(result.results), "payouts": len(result.payouts), "evaluations": evaluations,
        })
    except Exception as exc:
        _event({"at": now.astimezone().isoformat(), "event": "result_error", "race_id": race_id, "error": f"{type(exc).__name__}: {exc}"})


def _prediction_ids(race_id: str) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute("select prediction_id from predictions where race_id = ?", (race_id,))]


def _start_datetime(value: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})時(\d{2})分", value or "")
    return datetime.combine(TARGET_DATE, time(int(match.group(1)), int(match.group(2)))) if match else None


def _event(payload: dict) -> None:
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
