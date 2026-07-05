import asyncio
from datetime import date
import sqlite3

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.models import MeetingRace
from jra_srb.provider import HttpProvider
from jra_srb.service import JraService


DB_PATH = "data/analysis.sqlite"
BATCH_REPORT_SIZE = 100


def load_targets() -> list[tuple[str, date, str, int]]:
    with sqlite3.connect(DB_PATH) as conn:
        return [
            (race_id, date.fromisoformat(race_date), course, race_no)
            for race_id, race_date, course, race_no in conn.execute(
                """
                select r.race_id, r.race_date, r.course, r.race_no
                from races r
                left join runners ru on ru.race_id = r.race_id
                where r.race_date >= '2025-01-01'
                  and r.race_date <= '2025-12-31'
                group by r.race_id, r.race_date, r.course, r.race_no
                having count(ru.horse_no) = 0
                order by r.race_date, r.course, r.race_no
                """
            )
        ]


async def main() -> None:
    targets = load_targets()
    store = AnalysisSQLiteStore(DB_PATH)
    service = JraService(
        provider=HttpProvider(timeout=20, retries=1, max_concurrency=1, min_interval_seconds=0.05)
    )
    run_id = store.create_run(
        from_date=date(2025, 1, 1),
        to_date=date(2025, 12, 31),
        courses=["existing-2025-races"],
        include_card=True,
        include_odds=False,
        include_results=False,
        odds_timing="final_or_near_final",
    )
    failed = False
    print(f"run_id={run_id}")
    print(f"targets={len(targets)}")
    for index, (race_id, race_date, course, race_no) in enumerate(targets, start=1):
        try:
            card = await service.get_race_card_by_number(race_date, course, race_no)
            store.write_race(
                race_date,
                course,
                MeetingRace(race_no=race_no, race_id=race_id, race_name=card.race_name, start_time=card.start_time),
                source=card.source,
                fetched_at=card.fetched_at,
            )
            store.write_card(race_date, course, race_no, card)
        except Exception as exc:
            failed = True
            store.write_error(run_id, race_date, course, "card", exc, race_id, race_no)
            print(f"error={index}|{race_id}|{type(exc).__name__}|{exc}")
        if index % BATCH_REPORT_SIZE == 0:
            print(f"progress={index}/{len(targets)}")
    store.finish_run(run_id, "failed" if failed else "succeeded")
    print(f"finished={run_id}|status={'failed' if failed else 'succeeded'}")


if __name__ == "__main__":
    asyncio.run(main())
