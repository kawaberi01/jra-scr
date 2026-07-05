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


ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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


def write_markdown(output_path: Path, rows: list[dict[str, Any]]) -> None:
    md_path = output_path.with_suffix(".md")
    lines = [
        "# v17 Second Ticket Gap Sweep",
        "",
        "| phase | theory | gap | bet_races | tickets | ROI | no-max ROI | top3-cut ROI | axis_top3 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['phase']} | {row['theory_version']} | {row['second_middle_min_axis_score_gap']} | "
            f"{row['bet_races']} | {row['tickets']} | {row['return_rate']} | "
            f"{row['return_rate_without_max_payout']} | {row['return_rate_without_top3_payouts']} | "
            f"{row['axis_top3_rate']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--cache-dir", default=".workstate/jra-srb/prediction-v1-validation/netkeiba-cache")
    parser.add_argument(
        "--output",
        default=".workstate/jra-srb/prediction-v1-validation/v17_second_ticket_gap_sweep.json",
    )
    args = parser.parse_args()

    evaluator = load_evaluator()
    races = evaluator.load_rows(Path(args.db))
    db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(Path(args.db))
    base = evaluator.THEORIES["v17"]
    candidates = [
        replace(
            base,
            version="g6",
            score_note="v17 sweep: second middle axis-score gap > 6.0",
            second_middle_min_axis_score_gap=6.0,
        ),
        replace(
            base,
            version="g7_5",
            score_note="v17 sweep: second middle axis-score gap > 7.5",
            second_middle_min_axis_score_gap=7.5,
        ),
        replace(
            base,
            version="g10",
            score_note="v17 sweep: second middle axis-score gap > 10.0",
            second_middle_min_axis_score_gap=10.0,
        ),
        replace(
            base,
            version="g12_5",
            score_note="v17 sweep: second middle axis-score gap > 12.5",
            second_middle_min_axis_score_gap=12.5,
        ),
        replace(
            base,
            version="g15",
            score_note="v17 sweep: second middle axis-score gap > 15.0",
            second_middle_min_axis_score_gap=15.0,
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
        validation["second_middle_min_axis_score_gap"] = theory.second_middle_min_axis_score_gap
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
            summary["second_middle_min_axis_score_gap"] = theory.second_middle_min_axis_score_gap
            rows.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(output_path, rows)


if __name__ == "__main__":
    asyncio.run(main())
