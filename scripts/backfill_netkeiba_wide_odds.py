from __future__ import annotations

import argparse
import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.models import RaceOdds
from jra_srb.netkeiba_extractors import parse_netkeiba_odds_payload
from jra_srb.netkeiba_provider import NetkeibaHttpProvider


def targets(db: Path, start: str, end: str) -> list[tuple[str, str]]:
    """Return mapped JRA races whose complete wide-odds table is absent."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            """
            select m.jra_race_id, m.netkeiba_race_id
            from netkeiba_race_mappings m
            join races r on r.race_id = m.jra_race_id
            where r.race_date between ? and ?
              and m.netkeiba_race_id is not null
              and not exists (
                  select 1
                  from netkeiba_odds_entries o
                  where o.netkeiba_race_id = m.netkeiba_race_id
                    and o.bet_type = 'wide'
              )
            order by r.race_date, m.jra_race_id
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing historical netkeiba wide-odds tables at a bounded rate."
    )
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = Path(args.db)
    pending = targets(db, args.from_date, args.to_date)
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"targets={len(pending)} interval={args.interval:g}s", flush=True)
    if args.dry_run:
        return

    store = AnalysisSQLiteStore(db)
    provider = NetkeibaHttpProvider(min_interval_seconds=args.interval, retries=1)
    saved = failed = empty = 0
    for index, (jra_id, netkeiba_id) in enumerate(pending, 1):
        try:
            # The odds API endpoint is sufficient for completed races.  Avoid the
            # separate view request so this bounded backfill sends one request/race.
            page = await provider.fetch_odds_api(netkeiba_id)
            wide = parse_netkeiba_odds_payload(page.content).get("wide", [])
            if not wide:
                empty += 1
                print(f"{index}/{len(pending)} empty {jra_id}", flush=True)
                continue
            odds = RaceOdds(
                race_id=netkeiba_id,
                entries=wide,
                bet_type="wide",
                fetched_at=datetime.now(UTC),
                source=page.source,
            )
            store.write_netkeiba_odds(odds, jra_race_id=jra_id, bet_type="wide")
            saved += 1
            if index % 25 == 0 or index == len(pending):
                print(f"{index}/{len(pending)} saved={saved} empty={empty} failed={failed}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"{index}/{len(pending)} failed {jra_id} {type(exc).__name__}: {exc}", flush=True)
    print(f"done saved={saved} empty={empty} failed={failed}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
