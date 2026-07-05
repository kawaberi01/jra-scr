from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"


def load_evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_v1_validation", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--races-json", required=True)
    args = parser.parse_args()

    rows = json.loads(Path(args.races_json).read_text(encoding="utf-8"))
    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["status"] != "evaluated":
            continue
        tickets = row.get("tickets") or []
        bet = row.get("bet", 0)
        payout = row.get("payout", 0)
        reason = row.get("reason") or ""
        if bet == 0 and reason.startswith("insufficient_middle_candidates:"):
            mode = "skip_insufficient"
        elif bet == 0:
            mode = "skip_other"
        elif bet == 100:
            mode = "bet_single_ticket"
        elif bet == 200:
            mode = "bet_two_tickets"
        else:
            mode = f"bet_{len(tickets)}tickets"
        item = buckets.setdefault(mode, {"races": 0, "bet": 0, "pay": 0, "hits": 0})
        item["races"] += 1
        item["bet"] += bet
        item["pay"] += payout
        item["hits"] += 1 if payout > 0 else 0

    for mode, item in sorted(buckets.items()):
        roi = item["pay"] / item["bet"] if item["bet"] else None
        hit = item["hits"] / item["races"] if item["races"] else None
        print(
            mode,
            int(item["races"]),
            int(item["bet"]),
            int(item["pay"]),
            round(roi, 4) if roi is not None else None,
            round(hit, 4) if hit is not None else None,
        )


if __name__ == "__main__":
    main()
