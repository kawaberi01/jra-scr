from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import gzip
import json
from pathlib import Path

from catboost import CatBoostRanker, Pool

from jra_srb.jra_history_dataset import build_history_dataset
from jra_srb.jra_lap_style_dataset import append_lap_style_features
from jra_srb.jra_recent_form_dataset import append_recent_form_features


DB = Path("data/db/analysis.sqlite")
OUTPUT = Path(".workstate/jra-srb/jra-ltr-validation")


def split_dates(records: list[dict]) -> dict[str, set[str]]:
    dates = sorted({record["race_date"] for record in records})
    first = len(dates) * 70 // 100
    second = len(dates) * 85 // 100
    return {"train": set(dates[:first]), "calibration": set(dates[first:second]), "external": set(dates[second:])}


def relevance(record: dict) -> int:
    return max(0, 4 - int(record["actual_rank"]))


def evaluate(records: list[dict], scores: list[float]) -> dict:
    by_race: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for record, score in zip(records, scores):
        by_race[record["race_id"]].append((record, float(score)))
    selected = [max(items, key=lambda item: (item[1], -int(item[0]["horse_no"])))[0] for items in by_race.values()]
    return {
        "races": len(selected),
        "top1_win_rate": sum(item["label_win"] for item in selected) / len(selected) if selected else 0.0,
        "top1_top3_rate": sum(item["label_top3"] for item in selected) / len(selected) if selected else 0.0,
        "mean_actual_rank": sum(item["actual_rank"] for item in selected) / len(selected) if selected else 0.0,
    }


def ranked_rows(records: list[dict], scores: list[float]) -> list[dict]:
    by_race: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for record, score in zip(records, scores):
        by_race[record["race_id"]].append((record, float(score)))
    output = []
    for items in by_race.values():
        for rank, (record, score) in enumerate(sorted(items, key=lambda item: (-item[1], int(item[0]["horse_no"]))), 1):
            output.append({**record, "ranker_score": score, "ranker_rank": rank})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe CatBoost race ranking validation.")
    parser.add_argument("--lap-style", action="store_true")
    parser.add_argument("--recent-form", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--theory", type=str)
    args = parser.parse_args()
    records, metadata = build_history_dataset(DB)
    if args.recent_form:
        records = append_recent_form_features(records)
        metadata["recent_form"] = True
    if args.lap_style:
        records, lap_metadata = append_lap_style_features(records, DB)
        metadata["lap_style"] = lap_metadata
    dates = split_dates(records)
    train = [record for record in records if record["race_date"] in dates["train"]]
    calibration = [record for record in records if record["race_date"] in dates["calibration"]]
    external = [record for record in records if record["race_date"] in dates["external"]]
    train_pool = Pool([record["features"] for record in train], label=[relevance(record) for record in train], group_id=[record["race_id"] for record in train])
    model = CatBoostRanker(loss_function="YetiRank", iterations=400, depth=6, learning_rate=0.05, l2_leaf_reg=8.0, random_seed=20260712, verbose=False, allow_writing_files=False)
    model.fit(train_pool)
    calibration_scores = model.predict(Pool([record["features"] for record in calibration], group_id=[record["race_id"] for record in calibration]))
    external_scores = model.predict(Pool([record["features"] for record in external], group_id=[record["race_id"] for record in external]))
    result = {
        "theory": args.theory or (
            "catboost_pairwise_ranker_recent_lap_v3" if args.lap_style and args.recent_form
            else "catboost_pairwise_ranker_recent_form_v2" if args.recent_form
            else "catboost_pairwise_ranker_lap_style_v1" if args.lap_style
            else "catboost_pairwise_ranker_v1"
        ),
        "method": "CatBoostRanker YetiRank; race_id group-wise ranking; no odds feature; pre-race history features only"
        + ("; recent-form features" if args.recent_form else "")
        + ("; historical lap/style features" if args.lap_style else ""),
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": metadata,
        "date_ranges": {name: [min(values), max(values)] for name, values in dates.items()},
        "metrics": {"calibration": evaluate(calibration, calibration_scores), "external": evaluate(external, external_scores)},
        "warning": "This evaluates ranking accuracy, not betting profitability. Hyperparameters were fixed before inspecting external results.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "catboost-ranker.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (args.output_dir / "catboost-ranker.md").write_text("\n".join(("# CatBoost順位学習の時系列外部評価", "", f"- 校正: {result['metrics']['calibration']}", f"- 外部: {result['metrics']['external']}", f"- 注意: {result['warning']}", "")), encoding="utf-8", newline="\r\n")
    with gzip.open(args.output_dir / "ranker-predictions.jsonl.gz", "wt", encoding="utf-8", newline="\n") as stream:
        for row in [*ranked_rows(calibration, calibration_scores), *ranked_rows(external, external_scores)]:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("LTR_STATUS=completed")


if __name__ == "__main__":
    main()
