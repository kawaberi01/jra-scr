from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from itertools import combinations
from pathlib import Path
import sys
from typing import Any, Callable


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
SWEEP_PATH = WORKSTATE_DIR / "sweep_v80_followup_filters.py"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_atoms() -> list[tuple[str, Callable[[dict[str, Any]], bool]]]:
    return [
        ("exclude_middle_same_course_top3_rate=ge_0_35", lambda row: row["middle_same_course_top3_rate"] != "ge_0_35"),
        ("exclude_middle_jockey_recent_top3_rate=0_15_0_25", lambda row: row["middle_jockey_recent_top3_rate"] != "0_15_0_25"),
        ("exclude_axis_odds=4_6", lambda row: row["axis_odds"] != "4_6"),
        ("exclude_odds_ratio=lt_2", lambda row: row["odds_ratio"] != "lt_2"),
        ("keep_middle_same_course_top3_rate=missing", lambda row: row["middle_same_course_top3_rate"] == "missing"),
        ("keep_axis_odds=le_2_5", lambda row: row["axis_odds"] == "le_2_5"),
    ]


def evaluate_pairs(base_module: Any, records: list[dict[str, Any]], *, min_validation_tickets: int, min_holdout_tickets: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    atoms = build_atoms()
    for (name1, pred1), (name2, pred2) in combinations(atoms, 2):
        name = f"{name1}__AND__{name2}"
        by_split: dict[str, dict[str, Any]] = {}
        for split, _, _ in base_module.SPLITS:
            subset = [row for row in records if row["split"] == split and pred1(row) and pred2(row)]
            by_split[split] = base_module.summarize(subset)
        train_no_maxs = [by_split[split]["no_max_roi"] for split, _, _ in base_module.SPLITS[:3]]
        if any(value is None for value in train_no_maxs):
            continue
        if by_split["validation_2025Q4"]["tickets"] < min_validation_tickets:
            continue
        if by_split["holdout_2026H1"]["tickets"] < min_holdout_tickets:
            continue
        rows.append(
            {
                "rule": name,
                "train_no_max_floor": min(train_no_maxs),
                "validation_no_max": by_split["validation_2025Q4"]["no_max_roi"],
                "holdout_no_max": by_split["holdout_2026H1"]["no_max_roi"],
                "by_split": by_split,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["train_no_max_floor"] if row["train_no_max_floor"] is not None else -9.0,
            row["validation_no_max"] if row["validation_no_max"] is not None else -9.0,
            row["holdout_no_max"] if row["holdout_no_max"] is not None else -9.0,
        ),
        reverse=True,
    )


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# v80 Follow-up Pair Sweep",
        "",
        "| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(rows[:30], start=1):
        lines.append(
            f"| {index} | {row['rule']} | {row['train_no_max_floor']} | {row['validation_no_max']} | "
            f"{row['holdout_no_max']} | {row['by_split']['wf1_2025_07']['tickets']} | "
            f"{row['by_split']['wf2_2025_08']['tickets']} | {row['by_split']['wf3_2025_09']['tickets']} | "
            f"{row['by_split']['validation_2025Q4']['tickets']} | {row['by_split']['holdout_2026H1']['tickets']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theory-version", default="v80")
    parser.add_argument("--min-validation-tickets", type=int, default=10)
    parser.add_argument("--min-holdout-tickets", type=int, default=15)
    parser.add_argument(
        "--output-json",
        default=str(WORKSTATE_DIR / "v80_followup_pair_sweep.json"),
    )
    parser.add_argument(
        "--output-md",
        default=str(WORKSTATE_DIR / "v80_followup_pair_sweep.md"),
    )
    args = parser.parse_args()

    base_module = load_module(SWEEP_PATH, "sweep_v80_followup_filters")
    records = await base_module.collect_ticket_records(base_module.load_evaluator(), args.theory_version)
    rows = evaluate_pairs(
        base_module,
        records,
        min_validation_tickets=args.min_validation_tickets,
        min_holdout_tickets=args.min_holdout_tickets,
    )
    Path(args.output_json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(Path(args.output_md), rows)
    print(f"wrote {args.output_json} and {args.output_md}; theory={args.theory_version}; candidates={len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
