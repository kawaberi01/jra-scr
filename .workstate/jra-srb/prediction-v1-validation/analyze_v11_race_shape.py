from __future__ import annotations

import asyncio
import argparse
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


def bucket_axis_odds(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 2.0:
        return "<=2.0"
    if value <= 4.0:
        return "2.1-4.0"
    if value <= 6.0:
        return "4.1-6.0"
    if value <= 8.0:
        return "6.1-8.0"
    return "8.1-10.0"


def bucket_gap(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 2.5:
        return "<=2.5"
    if value <= 5.0:
        return "2.5-5.0"
    if value <= 10.0:
        return "5.0-10.0"
    return ">10.0"


def bucket_ratio(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 2.0:
        return "<=2.0"
    if value <= 3.0:
        return "2.0-3.0"
    if value <= 5.0:
        return "3.0-5.0"
    return ">5.0"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theory-version", default="v11")
    parser.add_argument("--from-date", default="2025-10-01")
    parser.add_argument("--to-date", default="2025-12-31")
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

    by_axis_bucket = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})
    by_gap_bucket = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})
    by_ratio_bucket = defaultdict(lambda: {"bet": 0, "pay": 0, "hits": 0, "tickets": 0})

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
        if len(middles) < theory.min_middles_to_bet:
            continue

        tickets = []
        for middle in middles:
            tickets.append(tuple(sorted([str(axis["nk"].horse_no), str(middle["nk"].horse_no)], key=lambda value: int(value))))
        payout_by_combo = evaluator.wide_payout_map(result.payouts)
        ticket_payouts = [payout_by_combo.get(ticket, 0) for ticket in tickets]

        first_non_axis = next((candidate for candidate in ranked if candidate is not axis), None)
        first_gap = axis["score"] - first_non_axis["score"] if first_non_axis is not None else None
        first_middle_odds = evaluator.odds_to_float(middles[0]["nk"].win_odds) if middles else None
        axis_odds = evaluator.odds_to_float(axis["nk"].win_odds)
        odds_ratio = (first_middle_odds / axis_odds) if axis_odds and first_middle_odds else None

        for bucket_map, bucket in (
            (by_axis_bucket, bucket_axis_odds(axis_odds)),
            (by_gap_bucket, bucket_gap(first_gap)),
            (by_ratio_bucket, bucket_ratio(odds_ratio)),
        ):
            bucket_map[bucket]["bet"] += len(tickets) * 100
            bucket_map[bucket]["pay"] += sum(ticket_payouts)
            bucket_map[bucket]["hits"] += sum(1 for value in ticket_payouts if value > 0)
            bucket_map[bucket]["tickets"] += len(tickets)

    for title, bucket_map in (
        ("AXIS_ODDS", by_axis_bucket),
        ("FIRST_GAP", by_gap_bucket),
        ("ODDS_RATIO", by_ratio_bucket),
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
