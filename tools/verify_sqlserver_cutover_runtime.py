"""概要: 旧SQLiteをread-onlyで参照し、SQL Storeと稼働APIの保存済み応答を比較する。
作成日: 2026-10-15
入力: 保持したanalysis SQLite、採用済みSQL設定、loopback API URL。
出力: 秘密・業務本文を含めない件数・応答hash・互換性監査JSON。
実行例: uv run python tools/verify_sqlserver_cutover_runtime.py --analysis-sqlite data/db/analysis.sqlite --output ...
注意事項: 外部providerへ通信しない。SQL/SQLiteへの業務書込みを行わない。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

import httpx

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.sqlserver_store import SqlServerAnalysisStore
from jra_srb.storage_config import SqlServerSettings, storage_backend


def json_value(value):
    """既存応答モデルや配列を比較用のJSON値へ正規化する。"""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def digest(value) -> str:
    """JSONのキー順に依存しない応答hashを返す。"""
    return hashlib.sha256(json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def legacy_reader(path: Path):
    """旧Storeの初期化DDLを呼ばず、比較専用のread-only接続だけを与える。"""
    store = AnalysisSQLiteStore.__new__(AnalysisSQLiteStore)
    store.path = path

    @contextmanager
    def connect(*, read_only=False):
        """どの呼出しでも旧SQLiteの書込みをOS/SQLite側で拒否する。"""
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    store._connect = connect
    return store


def verify(args) -> dict:
    """保存済みJRA/NAR・予想・評価・購入・時点データのStore/HTTP互換性を検査する。"""
    if storage_backend() != "sqlserver":
        raise ValueError("稼働backendがSQL Serverではありません")
    if urlparse(args.api_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("検証対象HTTPはloopbackに限定されています")
    old = legacy_reader(args.analysis_sqlite)
    current = SqlServerAnalysisStore(SqlServerSettings.from_env())
    checks = []

    def compare(name, callback):
        """旧StoreとSQL Storeで同じ要求の公開応答値を比較する。"""
        previous, present = callback(old), callback(current)
        before, after = digest(previous), digest(present)
        checks.append({"name": name, "sqlite_sha256": before, "sql_sha256": after, "equal": before == after})
        if before != after:
            raise ValueError(f"保存済み応答不一致: {name}")
        return json_value(present)

    with old._connect(read_only=True) as connection:
        race_ids = [row[0] for row in connection.execute(
            "SELECT race_id FROM races WHERE EXISTS(SELECT 1 FROM race_card_snapshots c WHERE c.race_id=races.race_id AND c.source_kind='pre_race_card' AND c.runner_set_status='complete') ORDER BY race_date DESC,race_id DESC LIMIT 3")]
        nar = connection.execute("SELECT race_id FROM races WHERE length(race_id)=16 AND EXISTS(SELECT 1 FROM runners ru WHERE ru.race_id=races.race_id) ORDER BY race_date DESC,race_id DESC LIMIT 1").fetchone()
        if nar is not None and nar[0] not in race_ids:
            race_ids.append(nar[0])
        observations = [row[0] for row in connection.execute("SELECT DISTINCT race_id FROM jra_live_shadow_observations ORDER BY race_id DESC LIMIT 2")]
    http_checks = []
    with httpx.Client(base_url=args.api_url, timeout=60) as client:
        health = client.get("/health")
        if health.status_code != 200 or health.json() != {"status": "ok"}:
            raise ValueError("稼働APIのhealthに失敗しました")
        document = client.get("/openapi.json")
        document.raise_for_status()
        operations = [(method, path) for path, methods in document.json()["paths"].items() for method in methods if method in {"get", "post", "put", "patch", "delete"}]
        if len(operations) != 69:
            raise ValueError("稼働APIのHTTP operation数が69ではありません")

        def http_compare(path, expected):
            """保存済みデータ専用HTTPだけを呼び、Storeと同じ応答を検査する。"""
            response = client.get(path)
            response.raise_for_status()
            equal = digest(response.json()) == digest(expected)
            http_checks.append({"path": path, "status": response.status_code, "equal": equal})
            if not equal:
                raise ValueError(f"稼働HTTP応答不一致: {path}")

        for race_id in race_ids:
            snapshot = compare("snapshot:" + race_id, lambda store, rid=race_id: store.get_pre_race_snapshot(rid))
            if len(race_id) == 12:
                http_compare(f"/jra/races/{race_id}/pre-race-snapshot", snapshot)
            for bet_type in ("win", "wide"):
                timeline = compare(f"timeline:{race_id}:{bet_type}", lambda store, rid=race_id, bt=bet_type: store.get_odds_timeline(rid, bt))
                if len(race_id) == 12:
                    http_compare(f"/jra/races/{race_id}/odds-timeline?bet_type={bet_type}", timeline)
        predictions = compare("predictions", lambda store: store.list_prediction_records(limit=5))
        http_compare("/jra/predictions?limit=5", predictions)
        for item in predictions["items"][:2]:
            record = compare("prediction:" + item["prediction_id"], lambda store, pid=item["prediction_id"]: store.get_prediction_record(pid))
            http_compare("/jra/predictions/" + item["prediction_id"], record)
        evaluations = compare("evaluations", lambda store: store.list_evaluation_records(limit=5))
        http_compare("/jra/evaluations?limit=5", evaluations)
        for item in evaluations["items"][:2]:
            record = compare("evaluation:" + item["evaluation_id"], lambda store, eid=item["evaluation_id"]: store.get_evaluation_record(eid))
            http_compare("/jra/evaluations/" + item["evaluation_id"], record)
        summary = compare("evaluation_summary", lambda store: store.summarize_evaluations())
        http_compare("/jra/evaluations/summary", summary)
        bets = compare("bet_records", lambda store: store.list_bet_records(limit=20))
        http_compare("/bet-records?limit=20", bets)
        for item in bets["items"][:3]:
            record = compare("bet:" + item["bet_record_id"], lambda store, bid=item["bet_record_id"]: store.get_bet_record(bid))
            http_compare("/bet-records/" + item["bet_record_id"], record)
        for race_id in observations:
            page = compare("shadow:" + race_id, lambda store, rid=race_id: store.list_jra_live_shadow_observations(rid, limit=2))
            http_compare(f"/jra/races/{race_id}/live-shadow-observations?limit=2", page)
        for path in ("/stored/results", "/jobs/result-collections"):
            response = client.get(path)
            response.raise_for_status()
            http_checks.append({"path": path, "status": response.status_code, "total": response.json()["total"]})
    return {"backend": "sqlserver", "database": current.settings.database, "http_operations": len(operations),
            "store_checks": checks, "http_checks": http_checks, "provider_requests": 0, "business_writes": 0}


def main() -> int:
    """監査結果を保存し、不一致では非ゼロ終了する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-sqlite", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"observed_at_utc": datetime.now(UTC).isoformat()}
    try:
        report.update({"status": "passed", "result": verify(args)})
        code = 0
    except Exception as error:
        report.update({"status": "failed", "error_type": type(error).__name__})
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "error_type": report.get("error_type")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
