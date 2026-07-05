from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from itertools import combinations
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"
SPLITS = [
    ("wf1_2025_07", "2025-07-01", "2025-07-31"),
    ("wf2_2025_08", "2025-08-01", "2025-08-31"),
    ("wf3_2025_09", "2025-09-01", "2025-09-30"),
    ("validation_2025Q4", "2025-10-01", "2025-12-31"),
]


def load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("evaluate_v1_validation", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def odds_bucket(value: float | None, *, axis: bool) -> str:
    if value is None:
        return "missing"
    if axis:
        if value <= 2.5:
            return "le_2_5"
        if value <= 4.0:
            return "2_5_4"
        if value <= 6.0:
            return "4_6"
        return "gt_6"
    if value < 10.0:
        return "8_10"
    if value < 15.0:
        return "10_15"
    return "15_20"


def ratio_bucket(axis_odds: float | None, middle_odds: float | None) -> str:
    if axis_odds in (None, 0) or middle_odds is None:
        return "missing"
    ratio = middle_odds / axis_odds
    if ratio < 2.0:
        return "lt_2"
    if ratio < 3.5:
        return "2_3_5"
    if ratio < 5.0:
        return "3_5_5"
    return "ge_5"


def race_no_bucket(value: int) -> str:
    if value <= 5:
        return "r01_05"
    if value <= 8:
        return "r06_08"
    return "r09_12"


def field_bucket(value: int) -> str:
    if value <= 10:
        return "le_10"
    if value <= 13:
        return "11_13"
    return "ge_14"


async def collect_records(evaluator: Any, db_path: Path, theory_version: str) -> list[dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    for label, from_date, to_date in SPLITS:
        races = evaluator.load_rows(db_path)
        db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(db_path)
        history = evaluator.build_history(races, from_date)
        theory = evaluator.THEORIES[theory_version]
        race_ids = evaluator.race_ids_in_period(races, from_date, to_date)
        provider = evaluator.DiskCachedNetkeibaProvider(
            inner=None,
            cache_dir=WORKSTATE_DIR / "netkeiba-cache",
            offline=True,
            max_live_requests=0,
        )
        service = evaluator.NetkeibaService(provider=provider)
        for race_id in race_ids:
            result = db_results_by_jra.get(race_id)
            if result is None:
                continue
            evaluation = await evaluator.evaluate_race(
                service, races, history, db_results_by_jra, nk_by_jra, race_id, theory
            )
            if evaluation.status != "evaluated" or not evaluation.tickets:
                continue
            race = races[race_id][0]
            by_no = {str(item.horse_no): item for item in result.results}
            axis = by_no.get(str(evaluation.axis_no))
            axis_odds = evaluator.odds_to_float(axis.win_odds) if axis else evaluation.axis_odds
            axis_pop = evaluator.int_or_none(axis.popularity) if axis else None
            for index, ticket in enumerate(evaluation.tickets):
                payout = (evaluation.payouts or [0] * len(evaluation.tickets))[index]
                horse_nos = ticket.split("-")
                middle_no = next((value for value in horse_nos if value != str(evaluation.axis_no)), None)
                middle = by_no.get(str(middle_no)) if middle_no is not None else None
                middle_odds = evaluator.odds_to_float(middle.win_odds) if middle else None
                middle_pop = evaluator.int_or_none(middle.popularity) if middle else None
                all_records.append(
                    {
                        "split": label,
                        "payout": payout,
                        "race_no": race_no_bucket(int(race["race_no"])),
                        "course_code": evaluator.course_code(race_id),
                        "surface": str(race.get("surface") or "missing"),
                        "field_size": field_bucket(int(race.get("field_size") or 0)),
                        "axis_odds": odds_bucket(axis_odds, axis=True),
                        "middle_odds": odds_bucket(middle_odds, axis=False),
                        "odds_ratio": ratio_bucket(axis_odds, middle_odds),
                        "axis_popularity": str(axis_pop if axis_pop is not None else "missing"),
                        "middle_popularity": str(middle_pop if middle_pop is not None else "missing"),
                    }
                )
    return all_records


def metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    tickets = len(records)
    payout = sum(int(row["payout"]) for row in records)
    max_payout = max((int(row["payout"]) for row in records), default=0)
    return {
        "tickets": tickets,
        "roi": round(payout / (tickets * 100), 4) if tickets else None,
        "no_max_roi": round((payout - max_payout) / (tickets * 100), 4) if tickets else None,
        "max_payout": max_payout,
    }


def find_filters(records: list[dict[str, Any]], min_tickets: int) -> list[dict[str, Any]]:
    feature_names = [
        "race_no",
        "field_size",
        "axis_odds",
        "middle_odds",
        "odds_ratio",
        "axis_popularity",
        "middle_popularity",
        "surface",
    ]
    conditions = sorted({(name, row[name]) for row in records for name in feature_names})
    candidates: list[tuple[tuple[str, str], ...]] = [(condition,) for condition in conditions]
    for first, second in combinations(conditions, 2):
        if first[0] != second[0]:
            candidates.append((first, second))

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        by_split = {}
        ok = True
        for split, _, _ in SPLITS:
            subset = [
                row
                for row in records
                if row["split"] == split and all(row[name] == value for name, value in candidate)
            ]
            summary = metrics(subset)
            by_split[split] = summary
            if summary["tickets"] < min_tickets:
                ok = False
                break
        if not ok:
            continue
        train_floor = min(by_split[split]["no_max_roi"] for split, _, _ in SPLITS[:3])
        validation = by_split["validation_2025Q4"]["no_max_roi"]
        rows.append(
            {
                "conditions": [{"feature": name, "bucket": value} for name, value in candidate],
                "train_no_max_floor": train_floor,
                "validation_no_max": validation,
                "by_split": by_split,
            }
        )
    return sorted(rows, key=lambda row: (row["train_no_max_floor"], row["validation_no_max"]), reverse=True)


def write_markdown(output: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Ticket Shape Filter Search",
        "",
        "| rank | conditions | train no-max floor | validation no-max | wf1 tickets | wf2 tickets | wf3 tickets | validation tickets |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(rows[:30], start=1):
        cond = ", ".join(f"{item['feature']}={item['bucket']}" for item in row["conditions"])
        lines.append(
            f"| {index} | {cond} | {row['train_no_max_floor']} | {row['validation_no_max']} | "
            f"{row['by_split']['wf1_2025_07']['tickets']} | {row['by_split']['wf2_2025_08']['tickets']} | "
            f"{row['by_split']['wf3_2025_09']['tickets']} | {row['by_split']['validation_2025Q4']['tickets']} |"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--theory-version", default="v25")
    parser.add_argument("--min-tickets", type=int, default=20)
    parser.add_argument("--output-json", default=str(WORKSTATE_DIR / "ticket_shape_filter_search_v25.json"))
    parser.add_argument("--output-md", default=str(WORKSTATE_DIR / "ticket_shape_filter_search_v25.md"))
    args = parser.parse_args()

    evaluator = load_evaluator()
    records = await collect_records(evaluator, Path(args.db), args.theory_version)
    rows = find_filters(records, args.min_tickets)
    Path(args.output_json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(Path(args.output_md), rows)
    print(f"wrote {args.output_json} and {args.output_md}; candidates={len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
