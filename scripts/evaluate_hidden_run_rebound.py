"""Evaluate a hidden-run rebound theory using only completed historical data."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


CS = (0.03, 0.1, 0.3, 1.0)
PROBABILITY_THRESHOLDS = (0.15, 0.20, 0.25, 0.30, 0.35)


@dataclass(frozen=True)
class RunnerRow:
    race_id: str
    race_date: str
    horse_no: str
    horse_name: str
    rank: int
    popularity: int | None
    win_odds: float | None
    features: tuple[float | None, ...]


def _last_corner(value: Any, field_size: int) -> float | None:
    parts = str(value or "").split("-")
    return int(parts[-1]) / field_size if parts and parts[-1].isdigit() and field_size else None


def _pace(value: Any) -> float | None:
    try:
        laps = [float(item) for item in json.loads(value or "[]")]
    except (TypeError, ValueError):
        return None
    if len(laps) < 4:
        return None
    half = len(laps) // 2
    return mean(laps[:half]) - mean(laps[half:])


def _distance(value: Any) -> int:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return int(digits) if digits else 0


def _pair(value: str) -> tuple[str, str] | None:
    values = sorted((item for item in value.split("-") if item.isdigit()), key=int)
    return (values[0], values[1]) if len(values) == 2 else None


def load_data(db: Path):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute(
            """
            select r.race_id, r.race_date, r.surface, r.distance,
                   ru.horse_no, ru.horse_name, re.rank,
                   ne.popularity, ne.win_odds, ne.corner_order, ne.final_3f,
                   nr.race_laps_json
            from races r
            join runners ru on ru.race_id=r.race_id
            join result_entries re on re.race_id=r.race_id and re.horse_no=ru.horse_no
            left join netkeiba_result_entries ne on ne.jra_race_id=r.race_id and ne.horse_no=ru.horse_no
            left join netkeiba_race_results nr on nr.jra_race_id=r.race_id
            where r.race_date between '2024-01-01' and '2026-06-30'
              and re.rank is not null
            order by r.race_date, r.race_id, cast(ru.horse_no as integer)
            """
        )]
        wide_rows = conn.execute(
            """
            select jra_race_id, combination, odds, odds_min, odds_max
            from netkeiba_odds_entries where bet_type='wide' and jra_race_id is not null
            """
        ).fetchall()
        payout_rows = conn.execute(
            """
            select jra_race_id, combination, payout
            from netkeiba_payouts where bet_type='wide' and jra_race_id is not null
            """
        ).fetchall()
    finally:
        conn.close()

    wide: dict[tuple[str, tuple[str, str]], float] = {}
    for race_id, combination, exact, lower, upper in wide_rows:
        pair = _pair(str(combination))
        try:
            price = float(exact) if exact is not None else (float(lower) + float(upper)) / 2
        except (TypeError, ValueError):
            continue
        if pair:
            wide[(str(race_id), pair)] = price
    payouts = {}
    for race_id, combination, payout in payout_rows:
        pair = _pair(str(combination))
        if pair:
            payouts[(str(race_id), pair)] = int(payout or 0)
    return rows, wide, payouts


def build_runner_rows(raw: list[dict[str, Any]]) -> list[RunnerRow]:
    races: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        races[row["race_id"]].append(row)
    # Normalize closing speed inside each past race instead of comparing raw times
    # across distances and track conditions.
    for race_rows in races.values():
        field_size = len(race_rows)
        closing = sorted(float(row["final_3f"]) for row in race_rows if row.get("final_3f") is not None)
        for row in race_rows:
            row["field_size"] = field_size
            row["corner_ratio"] = _last_corner(row.get("corner_order"), field_size)
            row["finish_ratio"] = int(row["rank"]) / field_size
            row["position_gain"] = (
                row["corner_ratio"] - row["finish_ratio"] if row["corner_ratio"] is not None else None
            )
            row["final3f_percentile"] = (
                closing.index(float(row["final_3f"])) / max(len(closing) - 1, 1)
                if closing and row.get("final_3f") is not None else None
            )
            row["pace_delta"] = _pace(row.get("race_laps_json"))

    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    result: list[RunnerRow] = []
    by_date: dict[str, list[str]] = defaultdict(list)
    for race_id, race_rows in races.items():
        by_date[race_rows[0]["race_date"]].append(race_id)
    for race_date in sorted(by_date):
        for race_id in sorted(by_date[race_date]):
            for row in races[race_id]:
                past = history[row["horse_name"]]
                recent = past[-3:]
                last = past[-1] if past else None
                features = (
                    float(last["rank"] - last["popularity"]) if last and last.get("popularity") else None,
                    last.get("final3f_percentile") if last else None,
                    last.get("position_gain") if last else None,
                    last.get("pace_delta") if last else None,
                    mean(item["rank"] - item["popularity"] for item in recent if item.get("popularity"))
                    if any(item.get("popularity") for item in recent) else None,
                    mean(item["final3f_percentile"] for item in recent if item.get("final3f_percentile") is not None)
                    if any(item.get("final3f_percentile") is not None for item in recent) else None,
                    mean(item["position_gain"] for item in recent if item.get("position_gain") is not None)
                    if any(item.get("position_gain") is not None for item in recent) else None,
                    float((date.fromisoformat(race_date) - date.fromisoformat(last["race_date"])).days) if last else None,
                    float(last.get("surface") == row.get("surface")) if last else None,
                    float(abs(_distance(last.get("distance")) - _distance(row.get("distance")))) if last else None,
                    0.8 / float(row["win_odds"]) if row.get("win_odds") else None,
                )
                if race_date >= "2025-01-01" and row.get("win_odds") is not None:
                    result.append(RunnerRow(
                        race_id=race_id, race_date=race_date, horse_no=str(row["horse_no"]),
                        horse_name=row["horse_name"], rank=int(row["rank"]),
                        popularity=int(row["popularity"]) if row.get("popularity") else None,
                        win_odds=float(row["win_odds"]), features=features,
                    ))
        for race_id in sorted(by_date[race_date]):
            for row in races[race_id]:
                history[row["horse_name"]].append(row)
    return result


def matrix(rows: list[RunnerRow]) -> np.ndarray:
    return np.asarray([[np.nan if value is None else value for value in row.features] for row in rows])


def summarize(rows, probabilities, threshold, wide, payouts):
    by_race: dict[str, list[tuple[RunnerRow, float]]] = defaultdict(list)
    all_by_race: dict[str, list[RunnerRow]] = defaultdict(list)
    for row, probability in zip(rows, probabilities, strict=True):
        all_by_race[row.race_id].append(row)
        if row.popularity is not None and 4 <= row.popularity <= 10 and row.win_odds and 5 <= row.win_odds <= 20:
            by_race[row.race_id].append((row, float(probability)))
    paid = []
    for race_id, candidates in by_race.items():
        field = all_by_race[race_id]
        anchor = min((row for row in field if row.win_odds), key=lambda row: row.win_odds, default=None)
        rebound, probability = max(candidates, key=lambda item: item[1])
        if anchor is None or probability < threshold or anchor.horse_no == rebound.horse_no:
            continue
        pair = tuple(sorted((anchor.horse_no, rebound.horse_no), key=int))
        price = wide.get((race_id, pair))
        if price is None or not 3 <= price <= 20:
            continue
        paid.append(payouts.get((race_id, pair), 0))
    paid.sort()
    bet = len(paid) * 100
    return {
        "tickets": len(paid), "hits": sum(value > 0 for value in paid),
        "return_rate": round(sum(paid) / bet, 4) if bet else 0.0,
        "no_max_return_rate": round(sum(paid[:-1]) / (bet - 100), 4) if len(paid) > 1 else 0.0,
        "no_top3_return_rate": round(sum(paid[:-3]) / (bet - 300), 4) if len(paid) > 3 else 0.0,
        "max_payout": max(paid, default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--output", default=".workstate/jra-srb/jra-hidden-rebound-validation/report.json")
    args = parser.parse_args()
    raw, wide, payouts = load_data(Path(args.db))
    rows = build_runner_rows(raw)
    train = [row for row in rows if row.race_date <= "2025-06-30"]
    q3 = [row for row in rows if "2025-07-01" <= row.race_date <= "2025-09-30"]
    q4 = [row for row in rows if "2025-10-01" <= row.race_date <= "2025-12-31"]
    h2 = q3 + q4
    candidates = []
    for c_value in CS:
        model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=c_value, max_iter=500, random_state=0))
        model.fit(matrix(train), np.asarray([row.rank <= 3 for row in train]))
        q3_probability = model.predict_proba(matrix(q3))[:, 1]
        q4_probability = model.predict_proba(matrix(q4))[:, 1]
        h2_probability = model.predict_proba(matrix(h2))[:, 1]
        for threshold in PROBABILITY_THRESHOLDS:
            q3_summary = summarize(q3, q3_probability, threshold, wide, payouts)
            q4_summary = summarize(q4, q4_probability, threshold, wide, payouts)
            h2_summary = summarize(h2, h2_probability, threshold, wide, payouts)
            candidates.append({"name": f"rebound_c{c_value:g}_p{threshold:.2f}", "q3": q3_summary, "q4": q4_summary, "h2": h2_summary,
                "pass": all(s["tickets"] >= 100 and s["return_rate"] >= 1 and s["no_max_return_rate"] >= 1 and s["no_top3_return_rate"] >= 1 for s in (q3_summary, q4_summary))})
    report = {"theory": "hidden-run-rebound-wide-v1", "candidate_count": len(candidates), "candidates": candidates,
              "eligible": [item["name"] for item in candidates if item["pass"]]}
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": len(candidates), "eligible": report["eligible"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
