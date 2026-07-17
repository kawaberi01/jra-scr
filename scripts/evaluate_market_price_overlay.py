"""Evaluate wide bets selected only by model-versus-market price disagreement.

The model never receives odds as an explanatory feature.  It estimates a pair's
probability of both horses finishing in the top three from information available
before the race, then compares it with the probability implied by the wide odds.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


TRAIN_END = "2025-06-30"
DEV_END = "2025-09-30"
MIN_WIDE_ODDS = 3.0
MAX_WIDE_ODDS = 20.0
TAKE_RATE = 0.775
CS = (0.01, 0.03, 0.1, 0.3, 1.0)
OVERLAY_THRESHOLDS = tuple(round(1.00 + 0.05 * index, 2) for index in range(10))

FEATURE_KEYS = (
    "starts", "avg_rank", "top3_rate", "recent_top3_rate", "recent_avg_rank",
    "same_surface_top3_rate", "same_course_top3_rate", "same_dist_top3_rate",
    "recent_corner_ratio", "recent_final_3f", "same_dist_final_3f", "recent_rank_std",
    "fast_pace_top3_rate", "same_surface_corner_ratio", "jockey_recent_top3_rate",
    "trainer_recent_top3_rate", "jockey_recent_same_surface_top3_rate",
    "trainer_recent_same_distance_bucket_top3_rate", "field_size", "race_no",
)


@dataclass(frozen=True)
class PairRow:
    race_id: str
    race_date: str
    pair: tuple[str, str]
    features: tuple[float | None, ...]
    hit: int
    market_probability: float
    payout: int


def _load_evaluator_module():
    path = Path(".workstate/jra-srb/prediction-v1-validation/evaluate_v1_validation.py")
    spec = importlib.util.spec_from_file_location("prediction_validation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pair_features(left: dict[str, Any], right: dict[str, Any]) -> tuple[float | None, ...]:
    values: list[float | None] = []
    for key in FEATURE_KEYS:
        a, b = _as_float(left.get(key)), _as_float(right.get(key))
        if a is None or b is None:
            values.extend((a, b))
        else:
            values.extend((min(a, b), max(a, b)))
    return tuple(values)


def _load_wide_market(db: Path) -> tuple[dict[str, dict[tuple[str, str], float]], dict[str, dict[tuple[str, str], int]]]:
    conn = sqlite3.connect(db)
    try:
        odds_rows = conn.execute(
            """
            select jra_race_id, combination, odds, odds_min, odds_max
            from netkeiba_odds_entries
            where bet_type = 'wide' and jra_race_id is not null
            """
        ).fetchall()
        payout_rows = conn.execute(
            """
            select jra_race_id, combination, payout
            from netkeiba_payouts
            where bet_type = 'wide' and jra_race_id is not null
            """
        ).fetchall()
    finally:
        conn.close()

    odds: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
    for race_id, combination, exact, lower, upper in odds_rows:
        values = sorted((str(value) for value in str(combination).split("-") if value.isdigit()), key=int)
        if len(values) != 2:
            continue
        price = _as_float(exact)
        if price is None:
            lo, hi = _as_float(lower), _as_float(upper)
            price = (lo + hi) / 2 if lo is not None and hi is not None else lo or hi
        if price and price > 0:
            odds[str(race_id)][tuple(values)] = price

    payouts: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    for race_id, combination, payout in payout_rows:
        values = sorted((str(value) for value in str(combination).split("-") if value.isdigit()), key=int)
        amount = int(payout or 0)
        if len(values) == 2 and amount > 0:
            payouts[str(race_id)][tuple(values)] = amount
    return odds, payouts


def _add_day_to_history(history: Any, race_rows: list[dict[str, Any]]) -> None:
    for row in race_rows:
        history.horses[row["horse_name"]].append(row)
        if row.get("jockey"):
            history.jockeys[str(row["jockey"])].append(row)
        if row.get("trainer"):
            history.trainers[str(row["trainer"])].append(row)


def build_pairs(db: Path) -> list[PairRow]:
    evaluator = _load_evaluator_module()
    races = evaluator.load_rows(db)
    odds_by_race, payouts_by_race = _load_wide_market(db)
    history = evaluator.HistoryBundle(defaultdict(list), defaultdict(list), defaultdict(list))
    result: list[PairRow] = []

    by_date: dict[str, list[str]] = defaultdict(list)
    for race_id, race_rows in races.items():
        date = race_rows[0]["race_date"]
        if date.startswith("2025"):
            by_date[date].append(race_id)
    for race_date in sorted(by_date):
        day_races = sorted(by_date[race_date])
        for race_id in day_races:
            race_rows = races[race_id]
            market = odds_by_race.get(race_id, {})
            if not market:
                continue
            enriched = []
            for row in race_rows:
                features = evaluator.hist_features(history.horses[row["horse_name"]], row, history)
                enriched.append((str(row["horse_no"]), features, int(row["rank"]) <= 3))
            by_no = {horse_no: (features, top3) for horse_no, features, top3 in enriched}
            for left, right in combinations(sorted(by_no, key=int), 2):
                pair = (left, right)
                price = market.get(pair)
                if price is None:
                    continue
                left_features, left_top3 = by_no[left]
                right_features, right_top3 = by_no[right]
                result.append(
                    PairRow(
                        race_id=race_id,
                        race_date=race_date,
                        pair=pair,
                        features=_pair_features(left_features, right_features),
                        hit=int(left_top3 and right_top3),
                        market_probability=TAKE_RATE / price,
                        payout=payouts_by_race.get(race_id, {}).get(pair, 0),
                    )
                )
        # Same-day results are unavailable at prediction time; only add them after
        # every race on that date has been feature-engineered.
        for race_id in day_races:
            _add_day_to_history(history, races[race_id])
    return result


def _matrix(rows: list[PairRow]) -> np.ndarray:
    return np.asarray([[np.nan if value is None else value for value in row.features] for row in rows])


def _summary(rows: list[PairRow], probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    by_race: dict[str, list[tuple[PairRow, float]]] = defaultdict(list)
    for row, probability in zip(rows, probabilities, strict=True):
        if MIN_WIDE_ODDS <= TAKE_RATE / row.market_probability <= MAX_WIDE_ODDS:
            by_race[row.race_id].append((row, float(probability) / row.market_probability))
    selected: list[PairRow] = []
    for candidates in by_race.values():
        row, overlay = max(candidates, key=lambda item: item[1])
        if overlay >= threshold:
            selected.append(row)
    payouts = [row.payout for row in selected]
    total_bet = len(selected) * 100
    total_payout = sum(payouts)
    trimmed = sorted(payouts)
    without_max = sum(trimmed[:-1]) if trimmed else 0
    without_top3 = sum(trimmed[:-3]) if len(trimmed) > 3 else 0
    return {
        "tickets": len(selected),
        "hits": sum(1 for payout in payouts if payout),
        "return_rate": round(total_payout / total_bet, 4) if total_bet else 0.0,
        "no_max_return_rate": round(without_max / max(total_bet - 100, 1), 4) if total_bet > 1 else 0.0,
        "no_top3_return_rate": round(without_top3 / max(total_bet - min(3, len(selected)) * 100, 1), 4) if len(selected) > 3 else 0.0,
        "max_payout": max(payouts, default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate market-price overlay wide theories.")
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--output", default=".workstate/jra-srb/jra-market-overlay-validation/report.json")
    args = parser.parse_args()

    rows = build_pairs(Path(args.db))
    train = [row for row in rows if row.race_date <= TRAIN_END]
    dev = [row for row in rows if TRAIN_END < row.race_date <= DEV_END]
    holdout = [row for row in rows if row.race_date > DEV_END]
    if not train or not dev or not holdout:
        raise RuntimeError(f"insufficient temporal split: train={len(train)} dev={len(dev)} holdout={len(holdout)}")

    candidates = []
    for c_value in CS:
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            # Price comparison requires calibrated absolute probabilities.  Class
            # balancing would deliberately distort that calibration upward.
            LogisticRegression(C=c_value, max_iter=500, random_state=0),
        )
        model.fit(_matrix(train), np.asarray([row.hit for row in train]))
        dev_probability = model.predict_proba(_matrix(dev))[:, 1]
        holdout_probability = model.predict_proba(_matrix(holdout))[:, 1]
        for threshold in OVERLAY_THRESHOLDS:
            dev_summary = _summary(dev, dev_probability, threshold)
            holdout_summary = _summary(holdout, holdout_probability, threshold)
            candidates.append({
                "name": f"overlay_c{c_value:g}_t{threshold:.2f}",
                "C": c_value,
                "overlay_threshold": threshold,
                "dev": dev_summary,
                "holdout": holdout_summary,
                "dev_pass": (
                    dev_summary["tickets"] >= 60
                    and dev_summary["return_rate"] >= 1.0
                    and dev_summary["no_max_return_rate"] >= 1.0
                ),
                "holdout_pass": (
                    holdout_summary["tickets"] >= 60
                    and holdout_summary["return_rate"] >= 1.0
                    and holdout_summary["no_max_return_rate"] >= 1.0
                    and holdout_summary["no_top3_return_rate"] >= 1.0
                ),
            })

    report = {
        "theory": "market-price-overlay-wide-v1",
        "principle": "odds are excluded from the pair probability model; buy only the highest model/market probability ratio per race",
        "market_probability": "0.775 / midpoint(wide odds range)",
        "wide_odds_band": [MIN_WIDE_ODDS, MAX_WIDE_ODDS],
        "splits": {"train_end": TRAIN_END, "dev_end": DEV_END},
        "rows": {"train": len(train), "dev": len(dev), "holdout": len(holdout)},
        "candidate_count": len(candidates),
        "candidates": candidates,
        "eligible": [item["name"] for item in candidates if item["dev_pass"] and item["holdout_pass"]],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": report["rows"], "candidate_count": len(candidates), "eligible": report["eligible"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
