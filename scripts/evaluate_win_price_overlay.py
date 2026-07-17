"""Evaluate win bets selected by model-versus-market probability disagreement."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_market_price_overlay import CS, FEATURE_KEYS, _as_float, _load_evaluator_module


TRAIN_END = "2025-06-30"
DEV_END = "2025-09-30"
TAKE_RATE = 0.80
MIN_WIN_ODDS = 3.0
MAX_WIN_ODDS = 30.0
OVERLAY_THRESHOLDS = tuple(round(1.00 + 0.05 * index, 2) for index in range(10))


@dataclass(frozen=True)
class HorseRow:
    race_id: str
    race_date: str
    horse_no: str
    features: tuple[float | None, ...]
    won: int
    market_probability: float
    win_odds: float
    payout: int


def _load_market(db: Path) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], int]]:
    conn = sqlite3.connect(db)
    try:
        odds_rows = conn.execute(
            """
            select jra_race_id, horse_no, win_odds
            from netkeiba_result_entries
            where jra_race_id is not null and win_odds is not null
            """
        ).fetchall()
        payout_rows = conn.execute(
            """
            select jra_race_id, combination, payout
            from netkeiba_payouts
            where bet_type = 'win' and jra_race_id is not null
            """
        ).fetchall()
    finally:
        conn.close()
    odds = {(str(race_id), str(horse_no)): float(value) for race_id, horse_no, value in odds_rows if float(value) > 0}
    payouts: dict[tuple[str, str], int] = {}
    for race_id, combination, payout in payout_rows:
        horse_no = "".join(character for character in str(combination) if character.isdigit())
        if horse_no:
            payouts[(str(race_id), str(int(horse_no)))] = int(payout or 0)
    return odds, payouts


def _append_history(history: Any, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        history.horses[row["horse_name"]].append(row)
        if row.get("jockey"):
            history.jockeys[str(row["jockey"])].append(row)
        if row.get("trainer"):
            history.trainers[str(row["trainer"])].append(row)


def build_rows(db: Path) -> list[HorseRow]:
    evaluator = _load_evaluator_module()
    races = evaluator.load_rows(db)
    odds, payouts = _load_market(db)
    history = evaluator.HistoryBundle(defaultdict(list), defaultdict(list), defaultdict(list))
    by_date: dict[str, list[str]] = defaultdict(list)
    for race_id, rows in races.items():
        race_date = rows[0]["race_date"]
        if race_date.startswith("2025"):
            by_date[race_date].append(race_id)

    result: list[HorseRow] = []
    for race_date in sorted(by_date):
        day_races = sorted(by_date[race_date])
        for race_id in day_races:
            for row in races[race_id]:
                horse_no = str(row["horse_no"])
                win_odds = odds.get((race_id, horse_no))
                if win_odds is None:
                    continue
                features = evaluator.hist_features(history.horses[row["horse_name"]], row, history)
                result.append(
                    HorseRow(
                        race_id=race_id,
                        race_date=race_date,
                        horse_no=horse_no,
                        features=tuple(_as_float(features.get(key)) for key in FEATURE_KEYS),
                        won=int(row["rank"] == 1),
                        market_probability=TAKE_RATE / win_odds,
                        win_odds=win_odds,
                        payout=payouts.get((race_id, horse_no), 0),
                    )
                )
        # Do not allow results from an earlier race on the same date into features.
        for race_id in day_races:
            _append_history(history, races[race_id])
    return result


def _matrix(rows: list[HorseRow]) -> np.ndarray:
    return np.asarray([[np.nan if value is None else value for value in row.features] for row in rows])


def _summary(rows: list[HorseRow], probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    by_race: dict[str, list[tuple[HorseRow, float]]] = defaultdict(list)
    for row, probability in zip(rows, probabilities, strict=True):
        if MIN_WIN_ODDS <= row.win_odds <= MAX_WIN_ODDS:
            by_race[row.race_id].append((row, float(probability) / row.market_probability))
    selected: list[HorseRow] = []
    for candidates in by_race.values():
        row, overlay = max(candidates, key=lambda item: item[1])
        if overlay >= threshold:
            selected.append(row)
    payouts = [row.payout for row in selected]
    total_bet = len(selected) * 100
    total_payout = sum(payouts)
    ordered = sorted(payouts)
    return {
        "tickets": len(selected),
        "hits": sum(1 for payout in payouts if payout > 0),
        "return_rate": round(total_payout / total_bet, 4) if total_bet else 0.0,
        "no_max_return_rate": round(sum(ordered[:-1]) / (total_bet - 100), 4) if len(selected) > 1 else 0.0,
        "no_top3_return_rate": round(sum(ordered[:-3]) / (total_bet - 300), 4) if len(selected) > 3 else 0.0,
        "max_payout": max(payouts, default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate static win-market overlay theories.")
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--output", default=".workstate/jra-srb/jra-win-overlay-validation/report.json")
    args = parser.parse_args()
    rows = build_rows(Path(args.db))
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
            LogisticRegression(C=c_value, max_iter=500, random_state=0),
        )
        model.fit(_matrix(train), np.asarray([row.won for row in train]))
        dev_probability = model.predict_proba(_matrix(dev))[:, 1]
        holdout_probability = model.predict_proba(_matrix(holdout))[:, 1]
        for threshold in OVERLAY_THRESHOLDS:
            dev_summary = _summary(dev, dev_probability, threshold)
            holdout_summary = _summary(holdout, holdout_probability, threshold)
            candidates.append(
                {
                    "name": f"win_overlay_c{c_value:g}_t{threshold:.2f}",
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
                }
            )

    report = {
        "theory": "market-price-overlay-win-v1",
        "principle": "odds are excluded from the win-probability model; buy only the largest model/market probability ratio per race",
        "market_probability": "0.80 / final win odds",
        "win_odds_band": [MIN_WIN_ODDS, MAX_WIN_ODDS],
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
