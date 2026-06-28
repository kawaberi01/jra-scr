from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pickle
import sqlite3
from typing import Any


UTC = timezone.utc


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if datetime.now(UTC) >= entry.expires_at:
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = CacheEntry(
            value=value,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )


class SQLiteTTLCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get(self, key: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "select value_blob, expires_at from cache_entries where cache_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            value_blob, expires_at_raw = row
            expires_at = datetime.fromisoformat(expires_at_raw)
            if datetime.now(UTC) >= expires_at:
                conn.execute("delete from cache_entries where cache_key = ?", (key,))
                return None
            return pickle.loads(value_blob)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into cache_entries (cache_key, value_blob, expires_at)
                values (?, ?, ?)
                """,
                (key, pickle.dumps(value), expires_at.isoformat()),
            )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists cache_entries (
                    cache_key text primary key,
                    value_blob blob not null,
                    expires_at text not null
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)
