from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"
BASE_SPLITS = [
    ("wf1_2025_07", "2025-07-01", "2025-07-31"),
    ("wf2_2025_08", "2025-08-01", "2025-08-31"),
    ("wf3_2025_09", "2025-09-01", "2025-09-30"),
    ("validation_2025Q4", "2025-10-01", "2025-12-31"),
]
HOLDOUT_SPLIT = ("holdout_2026H1", "2026-01-01", "2026-06-28")


def load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("evaluate_v1_validation", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def add_bucket(store: dict[str, dict[str, int]], bucket: str, payout: int) -> None:
    row = store[bucket]
    row["tickets"] += 1
    row["bet"] += 100
    row["payout"] += payout
    if payout > 0:
        row["hits"] += 1
        row["max_payout"] = max(row["max_payout"], payout)


def summarize_bucket(row: dict[str, int]) -> dict[str, Any]:
    bet = row["bet"]
    payout = row["payout"]
    return {
        "tickets": row["tickets"],
        "hits": row["hits"],
        "bet": bet,
        "payout": payout,
        "roi": round(payout / bet, 4) if bet else None,
        "no_max_roi": round((payout - row["max_payout"]) / bet, 4) if bet else None,
        "max_payout": row["max_payout"],
    }


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


def distance_bucket(value: Any) -> str:
    try:
        distance = int(value)
    except (TypeError, ValueError):
        return "missing"
    if distance <= 1400:
        return "le_1400"
    if distance <= 1600:
        return "1401_1600"
    if distance <= 2000:
        return "1601_2000"
    return "gt_2000"


def field_bucket(value: int) -> str:
    if value <= 10:
        return "le_10"
    if value <= 13:
        return "11_13"
    return "ge_14"


async def collect_split(evaluator: Any, db_path: Path, theory_version: str, label: str, from_date: str, to_date: str):
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

    groups: dict[str, dict[str, dict[str, int]]] = {
        name: defaultdict(lambda: {"tickets": 0, "hits": 0, "bet": 0, "payout": 0, "max_payout": 0})
        for name in [
            "race_no",
            "course_code",
            "surface",
            "distance",
            "field_size",
            "axis_odds",
            "middle_odds",
            "odds_ratio",
            "axis_popularity",
            "middle_popularity",
        ]
    }

    for race_id in race_ids:
        result = db_results_by_jra.get(race_id)
        if result is None:
            continue
        evaluation = await evaluator.evaluate_race(service, races, history, db_results_by_jra, nk_by_jra, race_id, theory)
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

            add_bucket(groups["race_no"], race_no_bucket(int(race["race_no"])), payout)
            add_bucket(groups["course_code"], evaluator.course_code(race_id), payout)
            add_bucket(groups["surface"], str(race.get("surface") or "missing"), payout)
            add_bucket(groups["distance"], distance_bucket(race.get("distance")), payout)
            add_bucket(groups["field_size"], field_bucket(int(race.get("field_size") or 0)), payout)
            add_bucket(groups["axis_odds"], odds_bucket(axis_odds, axis=True), payout)
            add_bucket(groups["middle_odds"], odds_bucket(middle_odds, axis=False), payout)
            add_bucket(groups["odds_ratio"], ratio_bucket(axis_odds, middle_odds), payout)
            add_bucket(groups["axis_popularity"], str(axis_pop if axis_pop is not None else "missing"), payout)
            add_bucket(groups["middle_popularity"], str(middle_pop if middle_pop is not None else "missing"), payout)

    return {
        "split": label,
        "from_date": from_date,
        "to_date": to_date,
        "theory_version": theory_version,
        "groups": {
            name: {bucket: summarize_bucket(values) for bucket, values in sorted(group.items())}
            for name, group in groups.items()
        },
    }


def write_markdown(output: Path, rows: list[dict[str, Any]], theory_version: str) -> None:
    lines = ["# Ticket Shape Context Analysis", "", f"Theory: `{theory_version}`", ""]
    for feature in rows[0]["groups"]:
        lines.extend([f"## {feature}", "", "| split | bucket | tickets | ROI | no-max ROI | hits | max_payout |", "|---|---|---:|---:|---:|---:|---:|"])
        for row in rows:
            for bucket, values in row["groups"][feature].items():
                lines.append(
                    f"| {row['split']} | {bucket} | {values['tickets']} | {values['roi']} | "
                    f"{values['no_max_roi']} | {values['hits']} | {values['max_payout']} |"
                )
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--theory-version", default="v25")
    parser.add_argument("--output-json", default=str(WORKSTATE_DIR / "ticket_shape_context_v25.json"))
    parser.add_argument("--output-md", default=str(WORKSTATE_DIR / "ticket_shape_context_v25.md"))
    parser.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args()

    evaluator = load_evaluator()
    splits = list(BASE_SPLITS)
    if args.include_holdout:
        splits.append(HOLDOUT_SPLIT)
    rows = [
        await collect_split(evaluator, Path(args.db), args.theory_version, label, from_date, to_date)
        for label, from_date, to_date in splits
    ]
    Path(args.output_json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(Path(args.output_md), rows, args.theory_version)
    print(f"wrote {args.output_json} and {args.output_md}")


if __name__ == "__main__":
    asyncio.run(main())
