from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import importlib.util
from pathlib import Path
import sys

from jra_srb.netkeiba_provider import NetkeibaHttpProvider
from jra_srb.netkeiba_service import NetkeibaService


WORKSTATE_DIR = Path(".workstate/jra-srb/prediction-v1-validation")
EVALUATOR_PATH = WORKSTATE_DIR / "evaluate_v1_validation.py"
DB_PATH = Path("data/analysis.sqlite")
CACHE_DIR = WORKSTATE_DIR / "netkeiba-cache"


def load_evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_v1_validation", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bucket_pop(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value <= 3:
        return "<=3"
    if value <= 6:
        return "4-6"
    if value <= 9:
        return "7-9"
    return "10+"


def bucket_weight_diff(value: int | None) -> str:
    if value is None:
        return "unknown"
    abs_value = abs(value)
    if abs_value == 0:
        return "0"
    if abs_value <= 4:
        return "1-4"
    if abs_value <= 8:
        return "5-8"
    return "9+"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theory-version", default="v17")
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    args = parser.parse_args()

    evaluator = load_evaluator()
    races = evaluator.load_rows(DB_PATH)
    db_results_by_jra, nk_by_jra = evaluator.load_netkeiba_db_results(DB_PATH)
    theory = evaluator.THEORIES[args.theory_version]
    history = evaluator.build_history(races, args.from_date)
    race_ids = evaluator.race_ids_in_period(races, args.from_date, args.to_date)
    provider = evaluator.DiskCachedNetkeibaProvider(
        inner=NetkeibaHttpProvider(min_interval_seconds=5.0, timeout=15.0, retries=1),
        cache_dir=CACHE_DIR,
        offline=True,
        max_live_requests=0,
    )
    service = NetkeibaService(provider=provider)

    by_axis_pop = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})
    by_first_middle_pop = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})
    by_axis_weight_diff = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})
    by_first_middle_weight_diff = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})

    for race_id in race_ids:
        race_rows = races[race_id]
        meta = race_rows[0]
        result = db_results_by_jra[race_id]
        nk_by_name = {evaluator.norm_name(item.horse_name): item for item in result.results}
        candidates = []
        for row in race_rows:
            nk = nk_by_name.get(evaluator.norm_name(row["horse_name"]))
            if nk is None:
                continue
            hist = history[row["horse_name"]]
            if len(hist) < theory.min_history:
                continue
            candidates.append({"row": row, "nk": nk, "score": evaluator.score(evaluator.hist_features(hist, row), theory)})
        if len(candidates) < theory.min_candidates:
            continue
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        axis = next(
            (
                candidate
                for candidate in ranked
                if (odds := evaluator.odds_to_float(candidate["nk"].win_odds)) is not None and odds <= theory.axis_odds_max
            ),
            ranked[0],
        )
        middles = []
        for candidate in ranked:
            if candidate is axis:
                continue
            odds = evaluator.odds_to_float(candidate["nk"].win_odds)
            if odds is not None and theory.middle_odds_min <= odds <= theory.middle_odds_max:
                if (
                    middles
                    and theory.second_middle_min_axis_score_gap is not None
                    and axis["score"] - candidate["score"] <= theory.second_middle_min_axis_score_gap
                ):
                    continue
                middles.append(candidate)
            if len(middles) >= theory.max_middles:
                break
        single_middle_override = False
        if len(middles) < theory.min_middles_to_bet:
            if (
                len(middles) == 1
                and theory.single_middle_min_axis_score_gap is not None
                and theory.single_middle_min_odds_ratio is not None
            ):
                middle_odds = evaluator.odds_to_float(middles[0]["nk"].win_odds)
                axis_odds = evaluator.odds_to_float(axis["nk"].win_odds)
                odds_ratio = (middle_odds / axis_odds) if middle_odds is not None and axis_odds not in (None, 0) else None
                score_gap = axis["score"] - middles[0]["score"]
                if (
                    odds_ratio is not None
                    and odds_ratio > theory.single_middle_min_odds_ratio
                    and score_gap > theory.single_middle_min_axis_score_gap
                ):
                    single_middle_override = True
            if not single_middle_override:
                continue
        payout_by_combo = evaluator.wide_payout_map(result.payouts)
        tickets = []
        ticket_payouts = []
        for middle in middles:
            ticket = tuple(sorted([str(axis["nk"].horse_no), str(middle["nk"].horse_no)], key=lambda value: int(value)))
            tickets.append(ticket)
            ticket_payouts.append(payout_by_combo.get(ticket, 0))

        axis_pop = int_or_none(axis["nk"].popularity)
        first_middle = middles[0]
        middle_pop = int_or_none(first_middle["nk"].popularity)
        axis_weight_diff = int_or_none(axis["nk"].horse_weight_diff)
        middle_weight_diff = int_or_none(first_middle["nk"].horse_weight_diff)

        for bucket_map, bucket in (
            (by_axis_pop, bucket_pop(axis_pop)),
            (by_first_middle_pop, bucket_pop(middle_pop)),
            (by_axis_weight_diff, bucket_weight_diff(axis_weight_diff)),
            (by_first_middle_weight_diff, bucket_weight_diff(middle_weight_diff)),
        ):
            bucket_map[bucket]["bet"] += len(tickets) * 100
            bucket_map[bucket]["pay"] += sum(ticket_payouts)
            bucket_map[bucket]["hits"] += sum(1 for value in ticket_payouts if value > 0)
            bucket_map[bucket]["tickets"] += len(tickets)

    for title, bucket_map in (
        ("AXIS_POP", by_axis_pop),
        ("FIRST_MIDDLE_POP", by_first_middle_pop),
        ("AXIS_WEIGHT_DIFF", by_axis_weight_diff),
        ("FIRST_MIDDLE_WEIGHT_DIFF", by_first_middle_weight_diff),
    ):
        print(f"PERIOD {args.from_date}..{args.to_date} THEORY {args.theory_version}")
        print(title)
        for key, values in bucket_map.items():
            roi = values["pay"] / values["bet"] if values["bet"] else None
            hit = values["hits"] / values["tickets"] if values["tickets"] else None
            print(key, values["tickets"], round(roi, 4) if roi is not None else None, round(hit, 4) if hit is not None else None)
        print()


if __name__ == "__main__":
    asyncio.run(main())
