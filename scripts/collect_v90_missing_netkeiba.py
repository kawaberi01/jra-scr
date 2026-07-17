from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path
from time import monotonic

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.netkeiba_service import NetkeibaService


FROM_DATE = "2024-07-01"
TO_DATE = "2024-08-31"


def missing_targets(db_path: Path, limit: int) -> list[tuple[str, str]]:
    with sqlite3.connect(db_path) as conn:
        return [
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                """
                select r.race_id, m.netkeiba_race_id
                from races r
                join race_results rr on rr.race_id=r.race_id
                join netkeiba_race_mappings m on m.jra_race_id=r.race_id
                left join netkeiba_race_results n on n.netkeiba_race_id=m.netkeiba_race_id
                where r.race_date between ? and ?
                  and (n.netkeiba_race_id is null
                    or not exists (select 1 from netkeiba_result_entries e where e.netkeiba_race_id=m.netkeiba_race_id)
                    or not exists (select 1 from netkeiba_payouts p where p.netkeiba_race_id=m.netkeiba_race_id))
                order by r.race_date, r.race_id
                limit ?
                """,
                (FROM_DATE, TO_DATE, limit),
            )
        ]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-interval-seconds", type=float, default=5.0)
    parser.add_argument("--repeat-until-complete", action="store_true")
    args = parser.parse_args()

    service = NetkeibaService()
    store = AnalysisSQLiteStore(args.db)
    idle_batches = 0
    while True:
        targets = missing_targets(args.db, args.limit)
        if not targets:
            print("missing=0 collected=0 failed=0")
            return 0
        collected = 0
        failed = 0
        last_started: float | None = None
        for jra_race_id, netkeiba_race_id in targets:
            if last_started is not None:
                remaining = args.min_interval_seconds - (monotonic() - last_started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            last_started = monotonic()
            try:
                result = await service.get_race_result(netkeiba_race_id)
                if result.race_id != netkeiba_race_id:
                    raise ValueError(f"race id mismatch: requested={netkeiba_race_id} received={result.race_id}")
                store.write_netkeiba_result(result, jra_race_id=jra_race_id)
                collected += 1
            except Exception as exc:
                failed += 1
                print(f"failed jra={jra_race_id} netkeiba={netkeiba_race_id} error={type(exc).__name__}:{exc}")
        print(f"missing={len(targets)} collected={collected} failed={failed}", flush=True)
        if not args.repeat_until_complete:
            return 0 if failed == 0 else 2
        if collected == 0:
            idle_batches += 1
        else:
            idle_batches = 0
        if failed or idle_batches >= 3:
            return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
