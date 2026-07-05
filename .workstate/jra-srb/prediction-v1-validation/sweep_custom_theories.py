from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from jra_srb.netkeiba_provider import NetkeibaHttpProvider
from jra_srb.netkeiba_service import NetkeibaService


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"
TRAIN_SPLITS = [
    {
        "label": "wf1_2025_07",
        "from_date": "2025-07-01",
        "to_date": "2025-07-31",
    },
    {
        "label": "wf2_2025_08",
        "from_date": "2025-08-01",
        "to_date": "2025-08-31",
    },
    {
        "label": "wf3_2025_09",
        "from_date": "2025-09-01",
        "to_date": "2025-09-30",
    },
]


def load_evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_v1_validation", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def evaluate_period(
    evaluator: Any,
    races: dict[str, list[dict[str, Any]]],
    db_results_by_jra: dict[str, Any],
    nk_by_jra: dict[str, str],
    theory: Any,
    from_date: str,
    to_date: str,
    cache_dir: Path,
) -> dict[str, Any]:
    history = evaluator.build_history(races, from_date)
    race_ids = evaluator.race_ids_in_period(races, from_date, to_date)
    provider = evaluator.DiskCachedNetkeibaProvider(
        inner=NetkeibaHttpProvider(min_interval_seconds=5.0, timeout=15.0, retries=1),
        cache_dir=cache_dir,
        offline=True,
        max_live_requests=0,
    )
    service = NetkeibaService(provider=provider)
    evaluations = []
    reasons: Counter[str] = Counter()
    for race_id in race_ids:
        item = await evaluator.evaluate_race(service, races, history, db_results_by_jra, nk_by_jra, race_id, theory)
        evaluations.append(item)
        if item.status == "excluded":
            reasons[item.reason or "unknown"] += 1
    summary = evaluator.summarize(evaluations, theory, from_date, to_date)
    summary["top_exclusion_reasons"] = reasons.most_common(10)
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--cache-dir", default=".workstate/jra-srb/prediction-v1-validation/netkeiba-cache")
    parser.add_argument("--output", default=".workstate/jra-srb/prediction-v1-validation/custom_theory_sweep.json")
    args = parser.parse_args()

    evaluator = load_evaluator()
    races = evaluator.load_rows(Path(args.db))
    db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(Path(args.db))
    base = evaluator.THEORIES["v9"]
    candidates = [
        replace(
            base,
            version="s18_a15",
            score_note="sweep: v9 with middle_odds_max=18.0 axis_odds_max=15.0",
            middle_odds_max=18.0,
            axis_odds_max=15.0,
        ),
        replace(
            base,
            version="s19_a15",
            score_note="sweep: v9 with middle_odds_max=19.0 axis_odds_max=15.0",
            middle_odds_max=19.0,
            axis_odds_max=15.0,
        ),
        replace(
            base,
            version="s19_5_a15",
            score_note="sweep: v9 with middle_odds_max=19.5 axis_odds_max=15.0",
            middle_odds_max=19.5,
            axis_odds_max=15.0,
        ),
        replace(
            base,
            version="s20_a15",
            score_note="sweep: v9 with middle_odds_max=20.0 axis_odds_max=15.0",
            middle_odds_max=20.0,
            axis_odds_max=15.0,
        ),
        replace(
            base,
            version="s19_a10",
            score_note="sweep: v9 with middle_odds_max=19.0 axis_odds_max=10.0",
            middle_odds_max=19.0,
            axis_odds_max=10.0,
        ),
        replace(
            base,
            version="s19_5_a10",
            score_note="sweep: v9 with middle_odds_max=19.5 axis_odds_max=10.0",
            middle_odds_max=19.5,
            axis_odds_max=10.0,
        ),
        replace(
            base,
            version="s20_a10",
            score_note="sweep: v9 with middle_odds_max=20.0 axis_odds_max=10.0",
            middle_odds_max=20.0,
            axis_odds_max=10.0,
        ),
    ]

    rows: list[dict[str, Any]] = []
    cache_dir = Path(args.cache_dir)
    for theory in candidates:
        validation = await evaluate_period(
            evaluator=evaluator,
            races=races,
            db_results_by_jra=db_results_by_jra,
            nk_by_jra=nk_by_jra,
            theory=theory,
            from_date="2025-10-01",
            to_date="2025-12-31",
            cache_dir=cache_dir,
        )
        validation["phase"] = "validation_2025Q4"
        rows.append(validation)
        print(json.dumps(validation, ensure_ascii=False), flush=True)

        for split in TRAIN_SPLITS:
            summary = await evaluate_period(
                evaluator=evaluator,
                races=races,
                db_results_by_jra=db_results_by_jra,
                nk_by_jra=nk_by_jra,
                theory=theory,
                from_date=split["from_date"],
                to_date=split["to_date"],
                cache_dir=cache_dir,
            )
            summary["phase"] = split["label"]
            rows.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
