from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
