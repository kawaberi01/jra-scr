"""Score one pre-race JRA card with the research O1/O2 cross-pool model."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jra_srb.jra_history_dataset import FEATURE_NAMES, build_live_feature_records
from evaluate_jra_o1o2_movement import HISTORY_KEYS


URL = (
    "http://127.0.0.1:8000/jra/meetings/2026-09-27/nakayama/races/11/"
    "prediction-bundle?meeting_no=4&meeting_day=9&refresh=true"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--model", type=Path, default=Path(".workstate/jra-srb/jra-o1o2-cross-pool-v1/cross.joblib"))
    parser.add_argument("--output", type=Path, default=Path(".workstate/jra-srb/jra-o1o2-cross-pool-v1/live_20260927_nakayama11.json"))
    args = parser.parse_args()
    bundle = httpx.get(URL, timeout=90).json()
    card = SimpleNamespace(**bundle["card"])
    card.runners = [SimpleNamespace(**row) for row in card.runners]
    history = build_live_feature_records(args.db, target_date=date(2026, 9, 27), course="nakayama", card=card)
    history_by_no = {row["horse_no"]: row for row in history}
    odds = bundle["odds_summary"]["odds"]
    win = {row["combination"][0]: float(row["odds"]) for row in odds["win"] if row["odds"]}
    pairs = {tuple(row["combination"]): float(row["odds"]) for row in odds["quinella"] if row["odds"]}
    win_raw = {key: 1 / value for key, value in win.items()}
    pair_raw = {key: 1 / value for key, value in pairs.items()}
    win_total, pair_total = sum(win_raw.values()), sum(pair_raw.values())
    pair_marginal = {key: 0.0 for key in win}
    for (left, right), value in pair_raw.items():
        if left in pair_marginal and right in pair_marginal:
            pair_marginal[left] += value / (2 * pair_total)
            pair_marginal[right] += value / (2 * pair_total)
    feature_positions = [FEATURE_NAMES.index(key) for key in HISTORY_KEYS]
    keys, vectors = [], []
    for key, price in win.items():
        if key not in history_by_no or pair_marginal[key] <= 0:
            continue
        p_win = win_raw[key] / win_total
        form = [history_by_no[key]["features"][index] for index in feature_positions]
        keys.append(key)
        vectors.append((math.log(price), p_win, *form, math.log(pair_marginal[key] / p_win)))
    if len(keys) != len(win):
        raise ValueError("missing live horse or O2 marginal")
    model = joblib.load(args.model)
    raw = model.predict_proba(np.asarray(vectors))[:, 1]
    normalized = raw / raw.sum()
    rows = []
    for key, probability in zip(keys, normalized, strict=True):
        rows.append({
            "horse_no": key,
            "horse_name": history_by_no[key]["horse_name"],
            "win_odds": win[key],
            "model_win_probability": round(float(probability), 5),
            "market_win_probability": round(win_raw[key] / win_total, 5),
            "o2_marginal_probability": round(pair_marginal[key], 5),
            "expected_return": round(float(probability) * win[key], 3),
        })
    result = {
        "race_id": bundle["race_id"],
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "odds_fetched_at": bundle["odds_summary"]["fetched_at"],
        "card_fetched_at": bundle["card"]["fetched_at"],
        "runners": sorted(rows, key=lambda row: row["model_win_probability"], reverse=True),
        "research_only": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n").encode("utf-8"))
    print(json.dumps({"odds_fetched_at": result["odds_fetched_at"], "runners": [
        {"no": r["horse_no"], "odds": r["win_odds"], "p": r["model_win_probability"],
         "market_p": r["market_win_probability"], "o2_p": r["o2_marginal_probability"],
         "ev": r["expected_return"]} for r in result["runners"]
    ]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
