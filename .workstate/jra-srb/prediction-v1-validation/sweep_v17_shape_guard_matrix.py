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
    {"label": "wf1_2025_07", "from_date": "2025-07-01", "to_date": "2025-07-31"},
    {"label": "wf2_2025_08", "from_date": "2025-08-01", "to_date": "2025-08-31"},
    {"label": "wf3_2025_09", "from_date": "2025-09-01", "to_date": "2025-09-30"},
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
        "# v17 Shape Guard Matrix Sweep",
        "",
        "| phase | theory | axis_min | axis_max | ratio_min | ratio_max_excl | bet_races | tickets | ROI | no-max ROI | top3-cut ROI |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        ratio_max = row["standard_max_first_middle_odds_ratio_exclusive"]
        ratio_max_text = "-" if ratio_max is None else str(ratio_max)
        axis_min = row["standard_axis_odds_min_for_ratio_guard"]
        axis_min_text = "-" if axis_min is None else str(axis_min)
        lines.append(
            f"| {row['phase']} | {row['theory_version']} | {axis_min_text} | "
            f"{row['standard_axis_odds_max_for_ratio_guard']} | {row['standard_min_first_middle_odds_ratio']} | "
            f"{ratio_max_text} | {row['bet_races']} | {row['tickets']} | {row['return_rate']} | "
            f"{row['return_rate_without_max_payout']} | {row['return_rate_without_top3_payouts']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--cache-dir", default=".workstate/jra-srb/prediction-v1-validation/netkeiba-cache")
    parser.add_argument(
        "--output",
        default=".workstate/jra-srb/prediction-v1-validation/v17_shape_guard_matrix_sweep.json",
    )
    args = parser.parse_args()

    evaluator = load_evaluator()
    races = evaluator.load_rows(Path(args.db))
    db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(Path(args.db))
    base = evaluator.THEORIES["v17"]
    candidates = [
        replace(
            base,
            version="sg_a4_6_rle2",
            score_note="v17 shape guard: skip standard bets when axis odds are 4.0..6.0 and odds ratio <= 2.0",
            standard_axis_odds_min_for_ratio_guard=4.0,
            standard_axis_odds_max_for_ratio_guard=6.0,
            standard_min_first_middle_odds_ratio=2.0,
        ),
        replace(
            base,
            version="sg_a4_6_r2_3",
            score_note="v17 shape guard: skip standard bets when axis odds are 4.0..6.0 and odds ratio is 2.0..3.0",
            standard_axis_odds_min_for_ratio_guard=4.0,
            standard_axis_odds_max_for_ratio_guard=6.0,
            standard_min_first_middle_odds_ratio=2.0,
            standard_max_first_middle_odds_ratio_exclusive=3.0,
        ),
        replace(
            base,
            version="sg_a4_6_r3_5",
            score_note="v17 shape guard: skip standard bets when axis odds are 4.0..6.0 and odds ratio is 3.0..5.0",
            standard_axis_odds_min_for_ratio_guard=4.0,
            standard_axis_odds_max_for_ratio_guard=6.0,
            standard_min_first_middle_odds_ratio=3.0,
            standard_max_first_middle_odds_ratio_exclusive=5.0,
        ),
        replace(
            base,
            version="sg_a6_8_r2_3",
            score_note="v17 shape guard: skip standard bets when axis odds are 6.0..8.0 and odds ratio is 2.0..3.0",
            standard_axis_odds_min_for_ratio_guard=6.0,
            standard_axis_odds_max_for_ratio_guard=8.0,
            standard_min_first_middle_odds_ratio=2.0,
            standard_max_first_middle_odds_ratio_exclusive=3.0,
        ),
        replace(
            base,
            version="sg_a6_8_r3_5",
            score_note="v17 shape guard: skip standard bets when axis odds are 6.0..8.0 and odds ratio is 3.0..5.0",
            standard_axis_odds_min_for_ratio_guard=6.0,
            standard_axis_odds_max_for_ratio_guard=8.0,
            standard_min_first_middle_odds_ratio=3.0,
            standard_max_first_middle_odds_ratio_exclusive=5.0,
        ),
        replace(
            base,
            version="sg_a4_8_r3_5",
            score_note="v17 shape guard: skip standard bets when axis odds are 4.0..8.0 and odds ratio is 3.0..5.0",
            standard_axis_odds_min_for_ratio_guard=4.0,
            standard_axis_odds_max_for_ratio_guard=8.0,
            standard_min_first_middle_odds_ratio=3.0,
            standard_max_first_middle_odds_ratio_exclusive=5.0,
        ),
        replace(
            base,
            version="sg_a4_8_rle2",
            score_note="v17 shape guard: skip standard bets when axis odds are 4.0..8.0 and odds ratio <= 2.0",
            standard_axis_odds_min_for_ratio_guard=4.0,
            standard_axis_odds_max_for_ratio_guard=8.0,
            standard_min_first_middle_odds_ratio=2.0,
        ),
        replace(
            base,
            version="sg_a2_10_rle2",
            score_note="v17 shape guard: skip standard bets when axis odds are 2.0..10.0 and odds ratio <= 2.0",
            standard_axis_odds_min_for_ratio_guard=2.0,
            standard_axis_odds_max_for_ratio_guard=10.0,
            standard_min_first_middle_odds_ratio=2.0,
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
        validation["standard_axis_odds_min_for_ratio_guard"] = theory.standard_axis_odds_min_for_ratio_guard
        validation["standard_axis_odds_max_for_ratio_guard"] = theory.standard_axis_odds_max_for_ratio_guard
        validation["standard_min_first_middle_odds_ratio"] = theory.standard_min_first_middle_odds_ratio
        validation["standard_max_first_middle_odds_ratio_exclusive"] = theory.standard_max_first_middle_odds_ratio_exclusive
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
            summary["standard_axis_odds_min_for_ratio_guard"] = theory.standard_axis_odds_min_for_ratio_guard
            summary["standard_axis_odds_max_for_ratio_guard"] = theory.standard_axis_odds_max_for_ratio_guard
            summary["standard_min_first_middle_odds_ratio"] = theory.standard_min_first_middle_odds_ratio
            summary["standard_max_first_middle_odds_ratio_exclusive"] = theory.standard_max_first_middle_odds_ratio_exclusive
            rows.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(output_path, rows)


if __name__ == "__main__":
    asyncio.run(main())
