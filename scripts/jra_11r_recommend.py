from __future__ import annotations

import asyncio
from datetime import date, datetime
import json
import sqlite3

from jra_srb.service import JraService


COURSES = ("hakodate", "kokura", "fukushima")
RACE_IDS = {"hakodate": "202607110211", "kokura": "202607111011", "fukushima": "202607110311"}


async def main() -> None:
    service = JraService()
    output = []
    for course in COURSES:
        race_id = RACE_IDS[course]
        card, odds = await asyncio.gather(
            service.get_race_card_by_number(date(2026, 7, 11), course, 11),
            service.get_race_odds(race_id, bet_types=["win", "wide", "quinella"], refresh=True),
        )
        prediction, tickets = _load(race_id)
        odds_maps = {
            bet_type: {"-".join(entry.combination): entry.odds for entry in entries}
            for bet_type, entries in odds.odds.items()
        }
        output.append({
            "course": course,
            "race_id": race_id,
            "race_name": card.race_name,
            "start_time": card.start_time,
            "fetched_at": odds.fetched_at.isoformat(),
            "track_condition": card.track_condition,
            "ranking": prediction.get("predicted_ranking", [])[:5],
            "saved_tickets": tickets,
            "current_odds": odds_maps,
        })
    print(json.dumps({"generated_at": datetime.now().astimezone().isoformat(), "races": output}, ensure_ascii=False, indent=2))


def _load(race_id: str):
    with sqlite3.connect("data/db/analysis.sqlite") as conn:
        row = conn.execute(
            "select prediction_id,prediction_json from predictions where race_id=? order by created_at limit 1", (race_id,)
        ).fetchone()
        tickets = conn.execute(
            "select bet_type,selection,amount,reason from prediction_tickets where prediction_id=? order by bucket", (row[0],)
        ).fetchall()
    return json.loads(row[1]), [dict(zip(("bet_type", "selection", "amount", "reason"), ticket)) for ticket in tickets]


if __name__ == "__main__":
    asyncio.run(main())
