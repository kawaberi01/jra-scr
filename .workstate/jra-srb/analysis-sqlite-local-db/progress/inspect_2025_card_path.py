import asyncio
from datetime import date

from jra_srb.provider import HttpProvider
from jra_srb.service import JraService


async def main() -> None:
    service = JraService(
        provider=HttpProvider(timeout=20, retries=1, max_concurrency=1, min_interval_seconds=0.2)
    )
    target_date = date(2025, 1, 5)
    course = "nakayama"
    meeting = await service.get_meeting(target_date, course)
    print(f"meeting={meeting.course}|races={len(meeting.races)}|source={meeting.source}")
    for race in meeting.races[:3] + meeting.races[-2:]:
        print(f"race={race.race_no}|{race.race_id}|card={race.card_cname}|odds={race.odds_cname}|result={race.result_cname}")
    card = await service.get_race_card_by_number(target_date, course, 11)
    first = card.runners[0] if card.runners else None
    print(f"card={card.race_id}|{card.race_name}|runners={len(card.runners)}|source={card.source}")
    if first is not None:
        print(f"first_runner={first.horse_no}|{first.horse_name}|{first.jockey}|{first.trainer}")


if __name__ == "__main__":
    asyncio.run(main())
