from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from jra_srb.netkeiba_provider import NetkeibaHttpProvider
from jra_srb.netkeiba_service import NetkeibaService


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"
DEFAULT_SPLITS = [
    {
        "label": "wf1_2025_07",
        "train_end": "2025-06-30",
        "from_date": "2025-07-01",
        "to_date": "2025-07-31",
    },
    {
        "label": "wf2_2025_08",
        "train_end": "2025-07-31",
        "from_date": "2025-08-01",
        "to_date": "2025-08-31",
    },
    {
        "label": "wf3_2025_09",
        "train_end": "2025-08-31",
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


async def evaluate_split(
    evaluator: Any,
    races: dict[str, list[dict[str, Any]]],
    db_results_by_jra: dict[str, Any],
    nk_by_jra: dict[str, str],
    theory: Any,
    split: dict[str, str],
    cache_dir: Path,
) -> tuple[dict[str, Any], Counter[str]]:
    history = evaluator.build_history(races, split["from_date"])
    race_ids = evaluator.race_ids_in_period(races, split["from_date"], split["to_date"])
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
    summary = evaluator.summarize(evaluations, theory, split["from_date"], split["to_date"])
    summary["split_label"] = split["label"]
    summary["train_end"] = split["train_end"]
    summary["top_exclusion_reasons"] = reasons.most_common(10)
    return summary, reasons


def write_outputs(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = output_path.with_suffix(".md")
    lines = [
        "# Train Walk-Forward Summary",
        "",
        "| split | theory | candidate | evaluated | excluded | bet_races | ROI | axis_top3 | no-max ROI |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['split_label']} | {row['theory_version']} | {row['candidate_races']} | "
            f"{row['evaluated_races']} | {row['excluded_races']} | {row['bet_races']} | "
            f"{row['return_rate']} | {row['axis_top3_rate']} | {row['return_rate_without_max_payout']} |"
        )
    lines.extend(["", "## Top Exclusion Reasons"])
    for row in rows:
        lines.append(f"- {row['split_label']} {row['theory_version']}: {row['top_exclusion_reasons']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--cache-dir", default=".workstate/jra-srb/prediction-v1-validation/netkeiba-cache")
    parser.add_argument("--output", default=".workstate/jra-srb/prediction-v1-validation/train_walkforward_summary.json")
    parser.add_argument("--theory-versions", default="v10")
    args = parser.parse_args()

    evaluator = load_evaluator()
    races = evaluator.load_rows(Path(args.db))
    db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(Path(args.db))
    versions = [value.strip() for value in args.theory_versions.split(",") if value.strip()]

    rows: list[dict[str, Any]] = []
    for version in versions:
        theory = evaluator.THEORIES[version]
        for split in DEFAULT_SPLITS:
            summary, _ = await evaluate_split(
                evaluator=evaluator,
                races=races,
                db_results_by_jra=db_results_by_jra,
                nk_by_jra=nk_by_jra,
                theory=theory,
                split=split,
                cache_dir=Path(args.cache_dir),
            )
            rows.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)

    write_outputs(Path(args.output), rows)


if __name__ == "__main__":
    asyncio.run(main())
