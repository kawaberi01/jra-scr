from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import JraService


def __getattr__(name: str):
    if name == "JraService":
        from .service import JraService

        globals()[name] = JraService
        return JraService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["JraService"]
