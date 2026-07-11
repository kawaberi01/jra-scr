from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Lock
from typing import Any


_CURRENT_REQUEST_TRACE_ID: ContextVar[str | None] = ContextVar("jra_srb_request_trace_id", default=None)


class PredictionTraceLogger:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def write(self, event_type: str, **fields: Any) -> None:
        if self.path is None:
            return
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=_json_default))
                handle.write("\n")


def build_prediction_trace_logger(path: str | Path | None) -> PredictionTraceLogger:
    return PredictionTraceLogger(path)


def set_current_request_trace_id(request_trace_id: str) -> Token[str | None]:
    return _CURRENT_REQUEST_TRACE_ID.set(request_trace_id)


def reset_current_request_trace_id(token: Token[str | None]) -> None:
    _CURRENT_REQUEST_TRACE_ID.reset(token)


def get_current_request_trace_id() -> str | None:
    return _CURRENT_REQUEST_TRACE_ID.get()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
