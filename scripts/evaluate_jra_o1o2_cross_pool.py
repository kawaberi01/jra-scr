"""Research win support disagreement between O1 and O2 at T-30m."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_jra_o1o2_movement import (
    HISTORY_KEYS,
    WIN_BAND,
    history_features,
    market,
    payout_map,
    read_races,
    sha256,
    split_for,
    summarize,
)


def samples(root: Path, *, include_later: bool = False) -> tuple[dict[str, list[dict]], dict[str, int]]:
    data = {split: [] for split in ("train", "dev", "holdout", "later") if include_later or split != "later"}
    audit: dict[str, int] = defaultdict(int)
    for race in read_races(root):
        split = split_for(race["race_date"])
        if split is None and include_later and race["race_date"] >= "2026-07-01":
            split = "later"
        if split is None:
            continue
        odds = race["inputs"]["odds"]["T-30m"]
        win = market(odds["win"], "win")
        quinella = market(odds["quinella"], "quinella")
        payouts = payout_map(race["result"]["win_payout_per_100_yen"], "win")
        runners = {str(r["horse_no"]): r for r in race["inputs"]["runners"]}
        if len(win) < 5 or len(quinella) < 10 or not payouts:
            audit[f"{split}_missing"] += 1
            continue
        win_raw = {key: 1 / price for key, price in win.items()}
        pair_raw = {key: 1 / price for key, price in quinella.items()}
        win_total, pair_total = sum(win_raw.values()), sum(pair_raw.values())
        pair_marginal = {key: 0.0 for key in win}
        for (left, right), value in pair_raw.items():
            if left in pair_marginal and right in pair_marginal:
                pair_marginal[left] += value / (2 * pair_total)
                pair_marginal[right] += value / (2 * pair_total)
        rows = []
        for key, price in win.items():
            if key not in runners or pair_marginal[key] <= 0:
                continue
            p_win = win_raw[key] / win_total
            p_pair = pair_marginal[key]
            form = history_features(runners[key])
            basic = (math.log(price), p_win, *form)
            cross = (*basic, math.log(p_pair / p_win))
            rows.append({
                "race_id": race["race_id"], "key": key, "price": price,
                "race_date": race["race_date"],
                "surface": race["race"].get("surface"),
                "distance": int(race["race"].get("distance") or 0),
                "payout": payouts.get(key, 0), "label": int(key in payouts),
                "market_probability": p_win,
                "basic": basic, "cross": cross,
            })
        if rows and any(row["label"] for row in rows):
            data[split].extend(rows)
            audit[f"{split}_races"] += 1
        else:
            audit[f"{split}_missing_winner"] += 1
    return data, dict(audit)


def score(model, rows: list[dict], variant: str) -> dict:
    probs = model.predict_proba(np.asarray([r[variant] for r in rows]))[:, 1]
    baseline = np.asarray([r["market_probability"] for r in rows])
    sprint_indices = [i for i, row in enumerate(rows) if row["surface"] == "turf" and row["distance"] <= 1400]
    sprint_rows = [rows[i] for i in sprint_indices]
    return {
        "model": summarize(rows, probs, WIN_BAND),
        "market": summarize(rows, baseline, WIN_BAND),
        "turf_sprint_model": summarize(sprint_rows, probs[sprint_indices], WIN_BAND),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-o1o2-cross-pool-v1"))
    args = parser.parse_args()
    data, audit = samples(args.data_root)
    report = {
        "hypothesis": "O2 pair-pool marginal support relative to O1 win support predicts win probability beyond O1 and pre-race form.",
        "decision_time": "T-30m",
        "data_root": str(args.data_root),
        "split": {"train": "through 2025-02-28", "dev": "2025-09-01 to 2025-12-31", "exploratory_2026": "2026-01-01 to 2026-06-30; previously used as holdout"},
        "audit": audit,
        "feature_names": {
            "basic": ["log_win_odds", "normalized_win_market_share", *HISTORY_KEYS],
            "cross": ["log_win_odds", "normalized_win_market_share", *HISTORY_KEYS, "log_o2_marginal_over_o1_share"],
        },
        "results": {},
        "limitations": ["Historical card identity and start times are mostly unverified", "O1/O2 were reconstructed after racing from publication times", "2026 was used in prior research and is not an independent holdout"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for variant in ("basic", "cross"):
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, solver="lbfgs"))
        model.fit(np.asarray([r[variant] for r in data["train"]]), np.asarray([r["label"] for r in data["train"]]))
        report["results"][variant] = {
            "dev": score(model, data["dev"], variant),
            "exploratory_2026": score(model, data["holdout"], variant),
        }
        model_path = args.output_dir / f"{variant}.joblib"
        joblib.dump(model, model_path)
        report["results"][variant]["artifact_sha256"] = sha256(model_path)
    (args.output_dir / "report.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n").encode("utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
