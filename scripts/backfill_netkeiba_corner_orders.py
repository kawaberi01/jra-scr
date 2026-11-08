"""概要: 既存の収集・集計を共通backendの保存済みデータに対して実行する。
作成日: 不明
入力: 従来のCLI引数、JRA_SRB_STORAGE_BACKENDとSQL接続設定。
出力: 従来の保存・集計・明示export。SQL運用時の業務正本はSQL Server。
実行例: uv run python scripts/backfill_netkeiba_corner_orders.py
注意事項: 取得処理は外部通信を行う。旧SQLiteへの自動fallbackは行わない。
"""

from __future__ import annotations

from jra_srb.storage import build_analysis_store, open_analysis_read

import argparse
import asyncio
import sqlite3
from pathlib import Path

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.netkeiba_provider import NetkeibaHttpProvider
from jra_srb.netkeiba_service import NetkeibaService


def targets(db: Path, start: str, end: str) -> list[tuple[str, str]]:
    """選択backendから不足する補完対象のレースを読み込む。"""
    conn = open_analysis_read(db)
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
    """従来の引数と取得条件に従い、選択backendで収集・集計を実行する。"""
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/db/analysis.sqlite")
    p.add_argument("--from-date", required=True)
    p.add_argument("--to-date", required=True)
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()
    db = Path(args.db)
    store = build_analysis_store(db)
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
