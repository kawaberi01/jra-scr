"""概要: 既存の業務Store契約をSQL Serverの通常writer領域へ接続する。
作成日: 2026-10-15
入力: reader/writer設定、適用済みmigration、API/collectorの業務入力。
出力: SQL Server上のanalysis業務データと既存の応答モデル。
実行例: uv run pytest -q tests/test_sqlserver_storage.py
注意事項: SQLiteを開かない。DB作成とbaseline採用は管理CLIで明示実行する。
"""

from __future__ import annotations

import json
import hashlib

from .analysis_store import AnalysisSQLiteStore
from .sqlserver_db import SqlServerConnection, SqlServerStorageError
from .sqlserver_schema import ANALYSIS_TABLES, CONTRACT
from .storage_config import SqlServerSettings
from .idempotency import entity_id, request_digest


class SqlServerAnalysisStore(AnalysisSQLiteStore):
    """既存Storeの業務処理を継承し、全SQLをSQL Serverで原子的に処理する。"""

    def __init__(self, settings: SqlServerSettings):
        """設定だけを保持し、SQLiteの初期化・起動時DDLを行わない。"""
        self.settings = settings

    def init_db(self) -> None:
        """明示migrationとbaseline検査の完了だけを確認し、DDLを実行しない。"""
        with self._connect(read_only=True) as connection:
            row = connection._raw(
                "SELECT value_json FROM api_runtime.storage_state WHERE state_key=N'baseline'"
            ).fetchone()
        if row is None:
            raise SqlServerStorageError("SQL Server baseline is not ready; run the explicit storage migration")
        state = json.loads(row[0])
        if state.get("version") != CONTRACT["version"] or state.get("status") != "ready":
            raise SqlServerStorageError("SQL Server baseline version or verification is incomplete")

    def _connect(self, *, read_only: bool = False) -> SqlServerConnection:
        """操作単位のreader/writer接続を作り、複数threadで共有しない。"""
        return SqlServerConnection(self.settings, ANALYSIS_TABLES, read_only=read_only)

    def _accept_write(self, conn, operation: str, race_id: str, payload: dict) -> bool:
        """同一受領の再試行を除き、入力版・受信時刻を業務更新と同じtransactionに保存する。"""
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        retry_digest = request_digest(operation, race_id) if operation in {"prediction_record", "bet_record"} else None
        if operation in {"prediction_record", "bet_record"} and retry_digest is None:
            return True
        business = json.loads(text)
        observed = business.get("card") if operation == "race_card" else business.get("odds") if operation == "odds" else business
        if isinstance(observed, dict) and operation in {"race_card", "odds", "race_result"}:
            # 同じ取得版へのcache hit/TTL応答メタデータは、新しい観測版にしない。
            observed.pop("cache_hit", None)
            observed.pop("meta", None)
        identity_text = json.dumps(business, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = retry_digest or hashlib.sha256((operation + "\n" + race_id + "\n" + identity_text).encode("utf-8")).digest()
        lock = hashlib.sha256((operation + "\n" + race_id).encode("utf-8")).hexdigest()
        result = conn._raw(
            "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=?,@LockMode='Exclusive',"
            "@LockOwner='Transaction',@LockTimeout=30000; SELECT @result AS lock_result;",
            ("jra-srb:" + lock,),
        ).fetchone()
        if result is None or result[0] < 0:
            raise SqlServerStorageError("SQL Server write serialization failed")
        existing = conn._raw("SELECT 1 FROM api_runtime.write_receipts WHERE request_sha256=?", (digest,)).fetchone()
        if existing is not None:
            return False
        conn._raw("INSERT api_runtime.write_receipts(request_sha256,operation,race_id,payload_json) VALUES(?,?,?,?)",
                  (digest, operation, race_id, text))
        return True

    def _entity_id(self, kind: str, identity: str) -> str:
        """明示された再試行キーがある業務作成だけに安定IDを割り当てる。"""
        return entity_id(kind, identity)

    def canonical_prediction_record(self, payload: dict) -> dict:
        """再試行時も初回保存の入力版と応答を返し、予想の再現性を維持する。"""
        digest = request_digest("prediction_record", str(payload["race_id"]))
        if digest is None:
            return payload
        with self._connect(read_only=True) as connection:
            row = connection._raw("SELECT payload_json FROM api_runtime.write_receipts WHERE request_sha256=?", (digest,)).fetchone()
        return json.loads(row[0]) if row else payload
