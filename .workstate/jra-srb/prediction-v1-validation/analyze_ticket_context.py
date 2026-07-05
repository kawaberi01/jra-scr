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


def rate_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value < 0.15:
        return "lt_0_15"
    if value < 0.25:
        return "0_15_0_25"
    if value < 0.35:
        return "0_25_0_35"
    return "ge_0_35"


def field_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 10:
        return "le_10"
    if value <= 13:
        return "11_13"
    return "ge_14"


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
        "middle_jockey_recent_top3_rate": defaultdict(lambda: {"tickets": 0, "hits": 0, "bet": 0, "payout": 0, "max_payout": 0}),
        "middle_trainer_recent_top3_rate": defaultdict(lambda: {"tickets": 0, "hits": 0, "bet": 0, "payout": 0, "max_payout": 0}),
        "middle_same_course_top3_rate": defaultdict(lambda: {"tickets": 0, "hits": 0, "bet": 0, "payout": 0, "max_payout": 0}),
        "middle_same_dist_top3_rate": defaultdict(lambda: {"tickets": 0, "hits": 0, "bet": 0, "payout": 0, "max_payout": 0}),
        "field_size": defaultdict(lambda: {"tickets": 0, "hits": 0, "bet": 0, "payout": 0, "max_payout": 0}),
    }

    for race_id in race_ids:
        result = db_results_by_jra.get(race_id)
        if result is None:
            continue
        evaluation = await evaluator.evaluate_race(service, races, history, db_results_by_jra, nk_by_jra, race_id, theory)
        if evaluation.status != "evaluated" or not evaluation.tickets:
            continue
        nk_by_name = {evaluator.norm_name(item.horse_name): item for item in result.results}
        feature_by_horse_no: dict[str, dict[str, float | None]] = {}
        for row in races[race_id]:
            nk = nk_by_name.get(evaluator.norm_name(row["horse_name"]))
            if nk is None:
                continue
            hist = history.horses[row["horse_name"]]
            if len(hist) < theory.min_history:
                continue
            feature_by_horse_no[str(nk.horse_no)] = evaluator.hist_features(hist, row, history)

        for index, ticket in enumerate(evaluation.tickets):
            payout = (evaluation.payouts or [0] * len(evaluation.tickets))[index]
            horse_nos = ticket.split("-")
            middle_no = next((value for value in horse_nos if value != str(evaluation.axis_no)), None)
            if middle_no is None:
                continue
            features = feature_by_horse_no.get(middle_no)
            if features is None:
                continue
            add_bucket(
                groups["middle_jockey_recent_top3_rate"],
                rate_bucket(features.get("jockey_recent_top3_rate")),
                payout,
            )
            add_bucket(
                groups["middle_trainer_recent_top3_rate"],
                rate_bucket(features.get("trainer_recent_top3_rate")),
                payout,
            )
            add_bucket(
                groups["middle_same_course_top3_rate"],
                rate_bucket(features.get("same_course_top3_rate")),
                payout,
            )
            add_bucket(
                groups["middle_same_dist_top3_rate"],
                rate_bucket(features.get("same_dist_top3_rate")),
                payout,
            )
            add_bucket(groups["field_size"], field_bucket(features.get("field_size")), payout)

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


def write_markdown(output: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# Ticket Context Analysis", "", "Theory: `v25`", ""]
    for feature in [
        "middle_jockey_recent_top3_rate",
        "middle_trainer_recent_top3_rate",
        "middle_same_course_top3_rate",
        "middle_same_dist_top3_rate",
        "field_size",
    ]:
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
    parser.add_argument("--output-json", default=str(WORKSTATE_DIR / "ticket_context_v25.json"))
    parser.add_argument("--output-md", default=str(WORKSTATE_DIR / "ticket_context_v25.md"))
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
    write_markdown(Path(args.output_md), rows)
    print(f"wrote {args.output_json} and {args.output_md}")


if __name__ == "__main__":
    asyncio.run(main())
