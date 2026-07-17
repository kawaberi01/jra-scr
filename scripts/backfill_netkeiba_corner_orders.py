from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.netkeiba_provider import NetkeibaHttpProvider
from jra_srb.netkeiba_service import NetkeibaService


def targets(db: Path, start: str, end: str) -> list[tuple[str, str]]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            """
            select m.jra_race_id, m.netkeiba_race_id
            from netkeiba_race_mappings m
            join races r on r.race_id = m.jra_race_id
            where r.race_date between ? and ? and m.netkeiba_race_id is not null
              and exists (select 1 from netkeiba_result_entries e where e.netkeiba_race_id=m.netkeiba_race_id)
              and not exists (select 1 from netkeiba_result_entries e where e.netkeiba_race_id=m.netkeiba_race_id and e.corner_order is not null and e.corner_order<>'')
            order by r.race_date, m.jra_race_id
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/db/analysis.sqlite")
    p.add_argument("--from-date", required=True)
    p.add_argument("--to-date", required=True)
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()
    db = Path(args.db)
    store = AnalysisSQLiteStore(db)
    service = NetkeibaService(NetkeibaHttpProvider(min_interval_seconds=args.interval, retries=1))
    for index, (jra_id, netkeiba_id) in enumerate(targets(db, args.from_date, args.to_date), 1):
        try:
            store.write_netkeiba_result(await service.get_race_result(netkeiba_id), jra_race_id=jra_id)
            if index % 25 == 0:
                print(f"{index} saved {jra_id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"{index} failed {jra_id} {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
