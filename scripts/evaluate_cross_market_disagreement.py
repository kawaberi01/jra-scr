"""Evaluate disagreement between JRA win and wide pari-mutuel pools."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MIN_WIDE_ODDS = 3.0
MAX_WIDE_ODDS = 20.0
VALUE_THRESHOLDS = tuple(round(1.1 + index * 0.1, 1) for index in range(10))
INFORMATION_THRESHOLDS = tuple(round(0.9 - index * 0.05, 2) for index in range(10))


@dataclass(frozen=True)
class Candidate:
    race_id: str
    race_date: str
    pair: tuple[str, str]
    price: float
    cross_ratio: float
    payout: int


def _pair(value: str) -> tuple[str, str] | None:
    values = sorted((item for item in value.split("-") if item.isdigit()), key=int)
    return (values[0], values[1]) if len(values) == 2 else None


def _price(exact: Any, lower: Any, upper: Any) -> float | None:
    try:
        if exact is not None:
            return float(exact)
        lo = float(lower) if lower is not None else None
        hi = float(upper) if upper is not None else None
        return (lo + hi) / 2 if lo is not None and hi is not None else lo or hi
    except (TypeError, ValueError):
        return None


def load_candidates(db: Path) -> list[Candidate]:
    conn = sqlite3.connect(db)
    try:
        dates = dict(conn.execute("select race_id, race_date from races where race_date like '2025%'").fetchall())
        win_rows = conn.execute(
            """
            select jra_race_id, horse_no, win_odds
            from netkeiba_result_entries
            where jra_race_id is not null and win_odds is not null
            """
        ).fetchall()
        wide_rows = conn.execute(
            """
            select jra_race_id, combination, odds, odds_min, odds_max
            from netkeiba_odds_entries
            where bet_type='wide' and jra_race_id is not null
            """
        ).fetchall()
        payout_rows = conn.execute(
            """
            select jra_race_id, combination, payout
            from netkeiba_payouts
            where bet_type='wide' and jra_race_id is not null
            """
        ).fetchall()
    finally:
        conn.close()

    wins: dict[str, dict[str, float]] = defaultdict(dict)
    for race_id, horse_no, odds in win_rows:
        if race_id in dates and float(odds) > 0:
            wins[str(race_id)][str(horse_no)] = float(odds)
    wides: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
    for race_id, combination, exact, lower, upper in wide_rows:
        pair = _pair(str(combination))
        price = _price(exact, lower, upper)
        if race_id in dates and pair and price and price > 0:
            wides[str(race_id)][pair] = price
    payouts: dict[tuple[str, tuple[str, str]], int] = {}
    for race_id, combination, payout in payout_rows:
        pair = _pair(str(combination))
        if pair:
            payouts[(str(race_id), pair)] = int(payout or 0)

    result: list[Candidate] = []
    for race_id, wide_prices in wides.items():
        win_prices = wins.get(race_id, {})
        if len(win_prices) < 2 or not wide_prices:
            continue
        win_inverse = {horse: 1.0 / odds for horse, odds in win_prices.items()}
        win_total = sum(win_inverse.values())
        win_share = {horse: value / win_total for horse, value in win_inverse.items()}
        wide_inverse = {pair: 1.0 / price for pair, price in wide_prices.items()}
        wide_total = sum(wide_inverse.values())
        wide_share = {pair: value / wide_total for pair, value in wide_inverse.items()}
        expected_raw = {
            pair: win_share.get(pair[0], 0.0) * win_share.get(pair[1], 0.0)
            for pair in wide_prices
        }
        expected_total = sum(expected_raw.values())
        if not expected_total or not wide_total:
            continue
        for pair, price in wide_prices.items():
            expected_share = expected_raw[pair] / expected_total
            observed_share = wide_share[pair]
            if observed_share <= 0:
                continue
            result.append(
                Candidate(
                    race_id=race_id,
                    race_date=str(dates[race_id]),
                    pair=pair,
                    price=price,
                    cross_ratio=expected_share / observed_share,
                    payout=payouts.get((race_id, pair), 0),
                )
            )
    return result


def select(rows: list[Candidate], direction: str, threshold: float) -> list[Candidate]:
    by_race: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        if MIN_WIDE_ODDS <= row.price <= MAX_WIDE_ODDS:
            by_race[row.race_id].append(row)
    selected = []
    for candidates in by_race.values():
        if direction == "value":
            row = max(candidates, key=lambda item: item.cross_ratio)
            if row.cross_ratio >= threshold:
                selected.append(row)
        else:
            row = min(candidates, key=lambda item: item.cross_ratio)
            if row.cross_ratio <= threshold:
                selected.append(row)
    return selected


def summarize(rows: list[Candidate]) -> dict[str, Any]:
    payouts = sorted(row.payout for row in rows)
    bet = len(rows) * 100
    return {
        "tickets": len(rows),
        "hits": sum(value > 0 for value in payouts),
        "return_rate": round(sum(payouts) / bet, 4) if bet else 0.0,
        "no_max_return_rate": round(sum(payouts[:-1]) / (bet - 100), 4) if len(rows) > 1 else 0.0,
        "no_top3_return_rate": round(sum(payouts[:-3]) / (bet - 300), 4) if len(rows) > 3 else 0.0,
        "max_payout": max(payouts, default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate win/wide cross-pool disagreement.")
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--output", default=".workstate/jra-srb/jra-cross-market-validation/report.json")
    args = parser.parse_args()
    rows = load_candidates(Path(args.db))
    periods = {
        "development_2025h1": [row for row in rows if row.race_date <= "2025-06-30"],
        "external_2025q3": [row for row in rows if "2025-07-01" <= row.race_date <= "2025-09-30"],
        "external_2025q4": [row for row in rows if row.race_date >= "2025-10-01"],
    }
    configs = [("value", value) for value in VALUE_THRESHOLDS] + [
        ("information", value) for value in INFORMATION_THRESHOLDS
    ]
    candidates = []
    for direction, threshold in configs:
        metrics = {
            period: summarize(select(period_rows, direction, threshold))
            for period, period_rows in periods.items()
        }
        passed = all(
            item["tickets"] >= 100
            and item["return_rate"] >= 1.0
            and item["no_max_return_rate"] >= 1.0
            and item["no_top3_return_rate"] >= 1.0
            for item in metrics.values()
        )
        candidates.append(
            {
                "name": f"cross_{direction}_{threshold:.2f}",
                "direction": direction,
                "threshold": threshold,
                "metrics": metrics,
                "pass": passed,
            }
        )
    report = {
        "theory": "win-wide-cross-pool-disagreement-v1",
        "definition": "expected wide pool share from normalized win shares divided by observed wide pool share",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "eligible": [item["name"] for item in candidates if item["pass"]],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": len(candidates), "eligible": report["eligible"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
