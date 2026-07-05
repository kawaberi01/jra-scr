from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from itertools import combinations
from pathlib import Path
import sys
from typing import Any


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
BASE_SWEEP_PATH = WORKSTATE_DIR / "sweep_v80_followup_filters.py"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# v86 All Pair Sweep",
        "",
        "| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(rows[:60], start=1):
        lines.append(
            f"| {index} | {row['rule']} | {row['train_no_max_floor']} | {row['validation_no_max']} | "
            f"{row['holdout_no_max']} | {row['by_split']['wf1_2025_07']['tickets']} | "
            f"{row['by_split']['wf2_2025_08']['tickets']} | {row['by_split']['wf3_2025_09']['tickets']} | "
            f"{row['by_split']['validation_2025Q4']['tickets']} | {row['by_split']['holdout_2026H1']['tickets']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theory-version", default="v86")
    parser.add_argument("--min-validation-tickets", type=int, default=10)
    parser.add_argument("--min-holdout-tickets", type=int, default=15)
    parser.add_argument(
        "--output-json",
        default=str(WORKSTATE_DIR / "v86_all_pair_sweep.json"),
    )
    parser.add_argument(
        "--output-md",
        default=str(WORKSTATE_DIR / "v86_all_pair_sweep.md"),
    )
    args = parser.parse_args()

    base = load_module(BASE_SWEEP_PATH, "sweep_v80_followup_filters")
    evaluator = base.load_evaluator()
    records = await base.collect_ticket_records(evaluator, args.theory_version)
    atoms = [(name, predicate) for name, predicate in base.build_rule_predicates() if name != "base_v80"]

    rows: list[dict[str, Any]] = []
    for (name1, pred1), (name2, pred2) in combinations(atoms, 2):
        by_split: dict[str, dict[str, Any]] = {}
        for split, _, _ in base.SPLITS:
            subset = [row for row in records if row["split"] == split and pred1(row) and pred2(row)]
            by_split[split] = base.summarize(subset)
        train_no_maxs = [by_split[split]["no_max_roi"] for split, _, _ in base.SPLITS[:3]]
        if any(value is None for value in train_no_maxs):
            continue
        if by_split["validation_2025Q4"]["tickets"] < args.min_validation_tickets:
            continue
        if by_split["holdout_2026H1"]["tickets"] < args.min_holdout_tickets:
            continue
        rows.append(
            {
                "rule": f"{name1}__AND__{name2}",
                "train_no_max_floor": min(train_no_maxs),
                "validation_no_max": by_split["validation_2025Q4"]["no_max_roi"],
                "holdout_no_max": by_split["holdout_2026H1"]["no_max_roi"],
                "by_split": by_split,
            }
        )

    rows.sort(
        key=lambda row: (
            row["train_no_max_floor"] if row["train_no_max_floor"] is not None else -9.0,
            row["validation_no_max"] if row["validation_no_max"] is not None else -9.0,
            row["holdout_no_max"] if row["holdout_no_max"] is not None else -9.0,
        ),
        reverse=True,
    )

    Path(args.output_json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(Path(args.output_md), rows)
    print(f"wrote {args.output_json} and {args.output_md}; theory={args.theory_version}; candidates={len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
