"""Compare static and moving O1/O2 markets without changing live predictions."""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


HISTORY_KEYS = (
    "horse_log_starts", "horse_win_rate", "horse_top3_rate",
    "horse_finish_strength", "horse_course_top3_rate",
    "horse_surface_top3_rate", "horse_distance_top3_rate",
    "jockey_win_rate", "jockey_top3_rate", "trainer_win_rate",
    "trainer_top3_rate", "days_since_last_scaled", "age_scaled",
    "is_newcomer", "is_obstacle",
)
SPLITS = ("train", "dev", "holdout")
WIN_BAND = (2.0, 30.0)
QUINELLA_BAND = (3.0, 100.0)
MIN_EXPECTED_RETURN = 1.05


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_for(date_text: str) -> str | None:
    if date_text <= "2025-02-28":
        return "train"
    if "2025-09-01" <= date_text <= "2025-12-31":
        return "dev"
    if "2026-01-01" <= date_text <= "2026-06-30":
        return "holdout"
    return None


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def market(snapshot: dict | None, kind: str) -> dict:
    if snapshot is None:
        return {}
    entries = snapshot["horses"] if kind == "win" else snapshot["pairs"]
    output = {}
    for row in entries:
        odds = number(row.get("odds"))
        if odds is None or odds <= 1 or row.get("status") != "numeric":
            continue
        if kind == "win":
            key = str(row["horse_no"])
        else:
            key = tuple(sorted((str(row["horse_no_1"]), str(row["horse_no_2"])), key=int))
        output[key] = odds
    return output


def history_features(runner: dict) -> tuple[float, ...]:
    features = runner["history_features"]
    return tuple(float(features[key]) for key in HISTORY_KEYS)


def pair_features(left: dict, right: dict) -> tuple[float, ...]:
    a, b = history_features(left), history_features(right)
    return tuple(value for pair in zip(a, b, strict=True) for value in (min(pair), max(pair)))


def payout_map(rows: list[dict], kind: str) -> dict:
    result = {}
    for row in rows:
        key = (str(row["horse_no"]) if kind == "win" else
               tuple(sorted((str(row["horse_no_1"]), str(row["horse_no_2"])), key=int)))
        result[key] = int(row["payout"])
    return result


def read_races(root: Path):
    for year in (2024, 2025, 2026):
        directory = root / str(year)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        data_path = directory / "races.jsonl.gz"
        if sha256(data_path) != manifest["files"]["races.jsonl.gz"]["sha256"]:
            raise ValueError(f"dataset hash mismatch: {data_path}")
        count = 0
        with gzip.open(data_path, "rt", encoding="utf-8") as stream:
            for line in stream:
                count += 1
                yield json.loads(line)
        if count != manifest["adopted_races"]:
            raise ValueError(f"dataset row count mismatch: {data_path}")


def build_samples(root: Path) -> tuple[dict, dict]:
    data = {kind: {split: [] for split in SPLITS} for kind in ("win", "quinella")}
    audit = defaultdict(int)
    seen = set()
    for race in read_races(root):
        split = split_for(race["race_date"])
        if split is None:
            audit["outside_fixed_period"] += 1
            continue
        race_id = race["race_id"]
        if race_id in seen:
            raise ValueError(f"duplicate race_id: {race_id}")
        seen.add(race_id)
        runners = {str(item["horse_no"]): item for item in race["inputs"]["runners"]}
        odds = race["inputs"]["odds"]
        audit[f"{split}_races"] += 1
        for kind in ("win", "quinella"):
            before = market(odds["T-30m"][kind], kind)
            decision = market(odds["T-10m"][kind], kind)
            total = sum(1.0 / price for price in decision.values())
            payouts = payout_map(race["result"][f"{kind}_payout_per_100_yen"], kind)
            if not before or not decision or total <= 0 or not payouts:
                audit[f"{split}_{kind}_incomplete_market_or_result"] += 1
                continue
            rows = []
            for key, price in decision.items():
                old_price = before.get(key)
                if old_price is None:
                    continue
                if kind == "win":
                    runner = runners.get(key)
                    if runner is None:
                        continue
                    form = history_features(runner)
                else:
                    left, right = (runners.get(horse_no) for horse_no in key)
                    if left is None or right is None:
                        continue
                    form = pair_features(left, right)
                market_probability = (1.0 / price) / total
                static = (math.log(price), market_probability, *form)
                moving = (*static, math.log(old_price / price))
                rows.append({"race_id": race_id, "key": key, "price": price,
                             "payout": payouts.get(key, 0), "label": int(key in payouts),
                             "market_probability": market_probability,
                             "static": static, "moving": moving})
            if not rows or not any(row["label"] for row in rows):
                audit[f"{split}_{kind}_incomplete_selection"] += 1
                continue
            data[kind][split].extend(rows)
            audit[f"{split}_{kind}_races"] += 1
    return data, dict(audit)


def summarize(rows: list[dict], probabilities: np.ndarray, band: tuple[float, float]) -> dict:
    groups = defaultdict(list)
    for row, probability in zip(rows, probabilities, strict=True):
        groups[row["race_id"]].append((row, float(probability)))
    race_log_loss = []
    selected = []
    for group in groups.values():
        total = sum(probability for _, probability in group)
        if total <= 0:
            raise ValueError("invalid model probability total")
        normalized = [(row, max(min(probability / total, 1 - 1e-9), 1e-9))
                      for row, probability in group]
        winners = [probability for row, probability in normalized if row["label"]]
        race_log_loss.append(-math.log(sum(winners)))
        candidates = [(row, probability * row["price"])
                      for row, probability in normalized if band[0] <= row["price"] <= band[1]]
        if candidates:
            choice, expected = max(candidates, key=lambda item: item[1])
            if expected >= MIN_EXPECTED_RETURN:
                selected.append(choice)
    returns = sorted(row["payout"] for row in selected)
    spent = 100 * len(selected)
    return {"races": len(groups), "runner_or_pair_rows": len(rows),
            "mean_race_log_loss": round(float(np.mean(race_log_loss)), 6),
            "tickets": len(selected), "hits": sum(value > 0 for value in returns),
            "stake_yen": spent, "return_yen": sum(returns),
            "roi": round(sum(returns) / spent, 4) if spent else None,
            "roi_without_max": round(sum(returns[:-1]) / (spent - 100), 4) if len(returns) > 1 else None,
            "roi_without_top3": round(sum(returns[:-3]) / (spent - 300), 4) if len(returns) > 3 else None}


def evaluate_kind(data: dict, kind: str) -> dict:
    train, dev, holdout = (data[split] for split in SPLITS)
    if not all((train, dev, holdout)):
        raise ValueError(f"empty chronological partition for {kind}")
    band = WIN_BAND if kind == "win" else QUINELLA_BAND
    result = {"splits": {split: {"races": len({row["race_id"] for row in data[split]}),
                                  "rows": len(data[split])} for split in SPLITS},
              "policies": {"odds_band": band, "min_expected_return": MIN_EXPECTED_RETURN,
                           "one_ticket_per_race": True, "stake_per_ticket_yen": 100},
              "models": {}}
    for variant in ("static", "moving"):
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, solver="lbfgs"))
        model.fit(np.asarray([row[variant] for row in train], dtype=np.float64),
                  np.asarray([row["label"] for row in train], dtype=np.int8))
        scores = {}
        for split in ("dev", "holdout"):
            rows = data[split]
            predicted = model.predict_proba(np.asarray([row[variant] for row in rows], dtype=np.float64))[:, 1]
            baseline = np.asarray([row["market_probability"] for row in rows])
            scores[split] = {"model": summarize(rows, predicted, band),
                             "market_baseline": summarize(rows, baseline, band),
                             "row_brier_model": round(float(brier_score_loss([row["label"] for row in rows], predicted)), 6),
                             "row_log_loss_model": round(float(log_loss([row["label"] for row in rows], predicted)), 6)}
        result["models"][variant] = scores
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    parser.add_argument("--output", type=Path,
                        default=Path(".workstate/jra-srb/jra-o1o2-movement-v1/report.json"))
    args = parser.parse_args()
    data, audit = build_samples(args.data_root)
    report = {"purpose": "shadow research only; no live model update",
              "split_policy": {"train": "through 2025-02-28", "dev": "2025-09-01 to 2025-12-31",
                               "holdout": "2026-01-01 to 2026-06-30"},
              "source_dataset": str(args.data_root), "source_audit": audit,
              "limitations": ["Historical card identity and start times are mostly unverified",
                              "Historical O1/O2 was retrieved after the race; this is a publication-time reconstruction",
                              "T-10m price selects a ticket; final payout settles it"],
              "win": evaluate_kind(data["win"], "win"),
              "quinella": evaluate_kind(data["quinella"], "quinella")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({kind: {variant: report[kind]["models"][variant]["holdout"]["model"]
                              for variant in ("static", "moving")}
                      for kind in ("win", "quinella")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
