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
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"
DB_PATH = Path("data/analysis.sqlite")
SPLITS = [
    ("wf1_2025_07", "2025-07-01", "2025-07-31"),
    ("wf2_2025_08", "2025-08-01", "2025-08-31"),
    ("wf3_2025_09", "2025-09-01", "2025-09-30"),
    ("validation_2025Q4", "2025-10-01", "2025-12-31"),
    ("holdout_2026H1", "2026-01-01", "2026-06-28"),
]


def load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("evaluate_v1_validation", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    tickets = len(records)
    payout = sum(int(row["payout"]) for row in records)
    max_payout = max((int(row["payout"]) for row in records), default=0)
    return {
        "tickets": tickets,
        "hits": sum(1 for row in records if int(row["payout"]) > 0),
        "roi": round(payout / (tickets * 100), 4) if tickets else None,
        "no_max_roi": round((payout - max_payout) / (tickets * 100), 4) if tickets else None,
        "max_payout": max_payout,
    }


async def collect_v75_ticket_records(evaluator: Any) -> list[dict[str, Any]]:
    races = evaluator.load_rows(DB_PATH)
    db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(DB_PATH)
    theory = evaluator.THEORIES["v75"]
    provider = evaluator.DiskCachedNetkeibaProvider(
        inner=None,
        cache_dir=WORKSTATE_DIR / "netkeiba-cache",
        offline=True,
        max_live_requests=0,
    )
    service = evaluator.NetkeibaService(provider=provider)
    out: list[dict[str, Any]] = []

    for split, from_date, to_date in SPLITS:
        history = evaluator.build_history(races, from_date)
        for race_id in evaluator.race_ids_in_period(races, from_date, to_date):
            result = db_results_by_jra.get(race_id)
            if result is None:
                continue
            evaluation = await evaluator.evaluate_race(
                service, races, history, db_results_by_jra, nk_by_jra, race_id, theory
            )
            if evaluation.status != "evaluated" or not evaluation.tickets:
                continue
            race_rows = races[race_id]
            race_meta = race_rows[0]
            nk_by_name = {evaluator.norm_name(item.horse_name): item for item in result.results}
            feature_by_horse_no: dict[str, dict[str, Any]] = {}
            for row in race_rows:
                nk = nk_by_name.get(evaluator.norm_name(row["horse_name"]))
                if nk is None:
                    continue
                hist = history.horses[row["horse_name"]]
                if len(hist) < theory.min_history:
                    continue
                feature_by_horse_no[str(nk.horse_no)] = evaluator.hist_features(hist, row, history)

            by_no = {str(item.horse_no): item for item in result.results}
            axis = by_no.get(str(evaluation.axis_no))
            axis_popularity = evaluator.int_or_none(axis.popularity) if axis else None
            axis_odds = evaluation.axis_odds
            for index, ticket in enumerate(evaluation.tickets):
                payout = (evaluation.payouts or [0] * len(evaluation.tickets))[index]
                horse_nos = ticket.split("-")
                middle_no = next((value for value in horse_nos if value != str(evaluation.axis_no)), None)
                if middle_no is None:
                    continue
                middle = by_no.get(str(middle_no))
                features = feature_by_horse_no.get(str(middle_no))
                if middle is None or features is None:
                    continue
                middle_odds = evaluator.odds_to_float(middle.win_odds)
                out.append(
                    {
                        "split": split,
                        "ticket": ticket,
                        "payout": payout,
                        "surface": str(race_meta.get("surface") or "missing"),
                        "axis_popularity": str(axis_popularity if axis_popularity is not None else "missing"),
                        "middle_popularity": str(
                            evaluator.int_or_none(middle.popularity) if middle is not None else "missing"
                        ),
                        "odds_ratio": ratio_bucket(axis_odds, middle_odds),
                        "middle_trainer_recent_top3_rate": evaluator.rate_bucket(
                            features.get("trainer_recent_top3_rate")
                        ),
                        "middle_same_course_top3_rate": evaluator.rate_bucket(
                            features.get("same_course_top3_rate")
                        ),
                        "middle_same_dist_top3_rate": evaluator.rate_bucket(
                            features.get("same_dist_top3_rate")
                        ),
                    }
                )
    return out


def build_rule_predicates() -> list[tuple[str, Callable[[dict[str, Any]], bool]]]:
    predicates: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("base_v75", lambda row: True),
        ("exclude_midpop_7", lambda row: row["middle_popularity"] != "7"),
        ("exclude_midpop_6_7", lambda row: row["middle_popularity"] not in {"6", "7"}),
        (
            "exclude_trainer_0_15_0_25",
            lambda row: row["middle_trainer_recent_top3_rate"] != "0_15_0_25",
        ),
        (
            "exclude_same_course_lt_0_15",
            lambda row: row["middle_same_course_top3_rate"] != "lt_0_15",
        ),
        ("exclude_ratio_lt2", lambda row: row["odds_ratio"] != "lt_2"),
        (
            "axis_le2_midpop_4_5",
            lambda row: row["axis_popularity"] in {"1", "2"} and row["middle_popularity"] in {"4", "5"},
        ),
        (
            "axis_le2_ex_trainer_0_15_0_25",
            lambda row: row["axis_popularity"] in {"1", "2"}
            and row["middle_trainer_recent_top3_rate"] != "0_15_0_25",
        ),
        (
            "axis_le2_ex_same_course_lt_0_15",
            lambda row: row["axis_popularity"] in {"1", "2"}
            and row["middle_same_course_top3_rate"] != "lt_0_15",
        ),
    ]
    base_atoms = [
        ("axis_popularity", "1"),
        ("axis_popularity", "2"),
        ("middle_popularity", "4"),
        ("middle_popularity", "5"),
        ("middle_popularity", "6"),
        ("middle_popularity", "7"),
        ("odds_ratio", "lt_2"),
        ("odds_ratio", "2_3_5"),
        ("odds_ratio", "3_5_5"),
        ("middle_trainer_recent_top3_rate", "0_15_0_25"),
        ("middle_trainer_recent_top3_rate", "lt_0_15"),
        ("middle_same_course_top3_rate", "lt_0_15"),
        ("middle_same_course_top3_rate", "missing"),
    ]
    for first, second in combinations(base_atoms, 2):
        if first[0] == second[0]:
            continue
        name = f"keep_{first[0]}={first[1]}__{second[0]}={second[1]}"
        predicates.append(
            (
                name,
                lambda row, first=first, second=second: row[first[0]] == first[1] and row[second[0]] == second[1],
            )
        )
    return predicates


def evaluate_predicates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, predicate in build_rule_predicates():
        by_split: dict[str, dict[str, Any]] = {}
        for split, _, _ in SPLITS:
            subset = [row for row in records if row["split"] == split and predicate(row)]
            by_split[split] = summarize(subset)
        train_no_maxs = [by_split[split]["no_max_roi"] for split, _, _ in SPLITS[:3]]
        if any(value is None for value in train_no_maxs):
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
        ),
        reverse=True,
    )


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# v75 Ticket Shape Filter Sweep",
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
    parser.add_argument(
        "--output-json",
        default=str(WORKSTATE_DIR / "v75_ticket_shape_filter_sweep.json"),
    )
    parser.add_argument(
        "--output-md",
        default=str(WORKSTATE_DIR / "v75_ticket_shape_filter_sweep.md"),
    )
    args = parser.parse_args()

    evaluator = load_evaluator()
    records = await collect_v75_ticket_records(evaluator)
    rows = evaluate_predicates(records)
    Path(args.output_json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(Path(args.output_md), rows)
    print(f"wrote {args.output_json} and {args.output_md}; candidates={len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
