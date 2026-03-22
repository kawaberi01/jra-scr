from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any


@lru_cache(maxsize=None)
def load_parser_config(name: str) -> dict[str, Any]:
    package = "jra_srb.config.parsers"
    resource = f"{name}.json"
    with resources.files(package).joinpath(resource).open("r", encoding="utf-8") as fh:
        return json.load(fh)
