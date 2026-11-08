"""概要: 既存の収集・集計を共通backendの保存済みデータに対して実行する。
作成日: 不明
入力: 従来のCLI引数、JRA_SRB_STORAGE_BACKENDとSQL接続設定。
出力: 従来の保存・集計・明示export。SQL運用時の業務正本はSQL Server。
実行例: uv run python scripts/jra_live_audit.py
注意事項: 取得処理は外部通信を行う。旧SQLiteへの自動fallbackは行わない。
"""

from __future__ import annotations

from jra_srb.storage import build_analysis_store, open_analysis_read
from jra_srb.storage_config import storage_backend

import json
from pathlib import Path
import sqlite3


DB_PATH = Path("data/db/analysis.sqlite")


def main() -> None:
    """従来の引数と取得条件に従い、選択backendで収集・集計を実行する。"""
    with open_analysis_read(DB_PATH) as conn:
        report = {
            "integrity_check": ("not_checked_sqlserver" if storage_backend() == "sqlserver" else conn.execute("pragma integrity_check").fetchone()[0]),
            "predictions": _scalar(conn, "select count(*) from predictions where race_id like '20260711%'"),
            "prediction_tickets": _scalar(conn, "select count(*) from prediction_tickets where race_id like '20260711%'"),
            "results": _scalar(conn, "select count(*) from race_results where race_id like '20260711%'"),
            "result_entries": _scalar(conn, "select count(*) from result_entries where race_id like '20260711%'"),
            "payouts": _scalar(conn, "select count(*) from payouts where race_id like '20260711%'"),
            "evaluations": _scalar(conn, "select count(*) from evaluations where race_id like '20260711%'"),
            "duplicate_predictions_by_race": conn.execute(
                "select race_id, count(*) from predictions where race_id like '20260711%' group by race_id having count(*) > 1"
            ).fetchall(),
            "prediction_without_result": [row[0] for row in conn.execute(
                "select distinct p.race_id from predictions p left join race_results r on r.race_id=p.race_id "
                "where p.race_id like '20260711%' and r.race_id is null order by p.race_id"
            )],
            "result_without_payout": [row[0] for row in conn.execute(
                "select r.race_id from race_results r left join payouts p on p.race_id=r.race_id "
                "where r.race_id like '20260711%' group by r.race_id having count(p.race_id)=0"
            )],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _scalar(conn: sqlite3.Connection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


if __name__ == "__main__":
    main()
