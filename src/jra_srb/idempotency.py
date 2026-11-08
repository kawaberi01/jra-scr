"""概要: 明示Idempotency-KeyによるPOST再試行を同じ業務IDへ対応させる。
作成日: 2026-10-15
入力: HTTPの任意Idempotency-Key、要求fingerprint、SQL設定。
出力: 要求文脈と決定的ID、異なる要求へのキー再利用の409判定。
実行例: uv run pytest -q tests/test_sqlserver_integration.py
注意事項: キー未指定時は従来の新規作成を維持する。HTTP取得中はDB接続を保持しない。
"""

from contextvars import ContextVar
import hashlib
from uuid import NAMESPACE_URL, uuid4, uuid5

from .errors import JraApiError


current_key: ContextVar[str | None] = ContextVar("jra_srb_idempotency_key", default=None)


class IdempotencyConflict(JraApiError):
    """同じ再試行キーが異なる要求に使われたことを表す。"""
    status_code = 409
    error_code = "idempotency_conflict"


def entity_id(kind: str, identity: str) -> str:
    """任意キーがある時だけ安定したIDを返し、通常の新規作成はUUID4を使う。"""
    key = current_key.get()
    return str(uuid5(NAMESPACE_URL, f"jra-srb:{key}:{kind}:{identity}")) if key else str(uuid4())


def request_digest(operation: str, identity: str) -> bytes | None:
    """明示再試行の業務操作を識別し、キー未指定時はNoneを返す。"""
    key = current_key.get()
    return hashlib.sha256(f"jra-srb:{key}:{operation}:{identity}".encode("utf-8")).digest() if key else None


def register_request(settings, key: str, fingerprint: bytes) -> None:
    """短い独立transactionでキーの要求内容を固定し、異なる再利用を拒否する。"""
    from .sqlserver_db import SqlServerConnection, SqlServerStorageError
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    with SqlServerConnection(settings, ()) as connection:
        result = connection._raw(
            "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=?,@LockMode='Exclusive',"
            "@LockOwner='Transaction',@LockTimeout=30000; SELECT @result AS lock_result;",
            ("jra-http:" + digest.hex(),),
        ).fetchone()
        if result is None or result[0] < 0:
            raise SqlServerStorageError("request key serialization failed")
        existing = connection._raw("SELECT request_fingerprint FROM api_runtime.request_keys WHERE key_sha256=?", (digest,)).fetchone()
        if existing is not None and bytes(existing[0]) != fingerprint:
            raise IdempotencyConflict("Idempotency-Key was already used for a different request")
        if existing is None:
            connection._raw("INSERT api_runtime.request_keys(key_sha256,request_fingerprint) VALUES(?,?)", (digest, fingerprint))
