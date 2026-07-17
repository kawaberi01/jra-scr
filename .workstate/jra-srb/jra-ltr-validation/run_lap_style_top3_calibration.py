from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path

from catboost import CatBoostClassifier
from sklearn.isotonic import IsotonicRegression

from jra_srb.jra_history_dataset import build_history_dataset
from jra_srb.jra_lap_style_dataset import append_lap_style_features


DB = Path("data/db/analysis.sqlite")
OUTPUT = Path(".workstate/jra-srb/jra-ltr-validation/lap-style-top3-v1")
THRESHOLDS = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60)


def split_dates(records: list[dict]) -> dict[str, set[str]]:
    dates = sorted({record["race_date"] for record in records})
    return {"train": set(dates[:len(dates) * 70 // 100]), "calibration": set(dates[len(dates) * 70 // 100:len(dates) * 85 // 100]), "external": set(dates[len(dates) * 85 // 100:])}


def top_rows(records: list[dict], probabilities: list[float], threshold: float) -> list[tuple[dict, float]]:
    grouped: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for record, probability in zip(records, probabilities):
        grouped[record["race_id"]].append((record, float(probability)))
    chosen = []
    for items in grouped.values():
        item = max(items, key=lambda value: (value[1], -int(value[0]["horse_no"])))
        if item[1] >= threshold:
            chosen.append(item)
    return chosen


def metrics(rows: list[tuple[dict, float]]) -> dict:
    return {"candidates": len(rows), "win_rate": sum(record["label_win"] for record, _ in rows) / len(rows) if rows else 0.0, "top3_rate": sum(record["label_top3"] for record, _ in rows) / len(rows) if rows else 0.0, "mean_probability": sum(probability for _, probability in rows) / len(rows) if rows else 0.0}


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe lap/style top3 calibration.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--theory", type=str, default="lap_style_top3_calibrated_v1")
    args = parser.parse_args()
    records, _ = build_history_dataset(DB)
    records, lap_metadata = append_lap_style_features(records, DB)
    dates = split_dates(records)
    train = [record for record in records if record["race_date"] in dates["train"]]
    calibration = [record for record in records if record["race_date"] in dates["calibration"]]
    external = [record for record in records if record["race_date"] in dates["external"]]
    model = CatBoostClassifier(loss_function="Logloss", iterations=400, depth=6, learning_rate=0.05, l2_leaf_reg=8.0, random_seed=20260713, verbose=False, allow_writing_files=False)
    model.fit([record["features"] for record in train], [record["label_top3"] for record in train])
    calibration_raw = model.predict_proba([record["features"] for record in calibration])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip").fit(calibration_raw, [record["label_top3"] for record in calibration])
    calibration_probabilities = calibrator.predict(calibration_raw)
    external_probabilities = calibrator.predict(model.predict_proba([record["features"] for record in external])[:, 1])
    trials = [{"threshold": threshold, "calibration": metrics(top_rows(calibration, calibration_probabilities, threshold))} for threshold in THRESHOLDS]
    viable = [item for item in trials if item["calibration"]["candidates"] >= 200]
    chosen = max(viable, key=lambda item: (item["calibration"]["top3_rate"], item["calibration"]["win_rate"])) if viable else None
    result = {"theory": args.theory, "method": "CatBoost top3 classifier with isotonic calibration; no odds feature; date-based split", "created_at": datetime.now(UTC).isoformat(), "lap_metadata": lap_metadata, "trials": trials, "chosen": chosen, "external": metrics(top_rows(external, external_probabilities, chosen["threshold"])) if chosen else None, "warning": "Accuracy-only model. It does not establish positive betting expected value."}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "top3-calibration.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (args.output_dir / "top3-calibration.md").write_text("\n".join(("# ラップ×脚質 3着内確率校正", "", f"- 条件: {chosen}", f"- 外部: {result['external']}", "")), encoding="utf-8", newline="\r\n")
    print("TOP3_CALIBRATION_STATUS=completed")


if __name__ == "__main__":
    main()
