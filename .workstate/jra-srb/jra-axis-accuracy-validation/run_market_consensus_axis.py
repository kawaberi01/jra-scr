from __future__ import annotations

from collections import defaultdict
import gzip
import json
from pathlib import Path


ARTIFACTS = Path(".workstate/jra-srb/jra-win-ev-revalidation/artifacts-2024-2026")
OUTPUT = Path(".workstate/jra-srb/jra-axis-accuracy-validation")
ODDS_CEILINGS = (2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0)


def load_rows() -> tuple[list[dict], dict[str, list[str]]]:
    with gzip.open(ARTIFACTS / "runner-predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    split = json.loads((ARTIFACTS / "split-metadata.json").read_text(encoding="utf-8"))["date_sets"]
    return rows, split


def selections(rows: list[dict], ceiling: float | None, mode: str) -> list[dict]:
    by_race: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_race[row["race_id"]].append(row)
    result = []
    for runners in by_race.values():
        market = min(runners, key=lambda item: (item["win_odds"], int(item["horse_no"])))
        model = max(runners, key=lambda item: (item["raw_win_probability"], -int(item["horse_no"])))
        selected = model if mode in {"model", "consensus"} else market
        if mode == "consensus" and market["horse_no"] != model["horse_no"]:
            continue
        if ceiling is not None and selected["win_odds"] > ceiling:
            continue
        result.append(selected)
    return result


def metrics(rows: list[dict]) -> dict:
    total = len(rows)
    return {
        "candidates": total,
        "win_rate": sum(row["label_win"] for row in rows) / total if total else 0.0,
        "top3_rate": sum(row["label_top3"] for row in rows) / total if total else 0.0,
        "mean_odds": sum(row["win_odds"] for row in rows) / total if total else 0.0,
    }


def main() -> None:
    rows, split = load_rows()
    calibration = [row for row in rows if row["race_date"] in set(split["calibration"])]
    external = [row for row in rows if row["race_date"] in set(split["external"])]
    iterations = [{"odds_ceiling": ceiling, "calibration": metrics(selections(calibration, ceiling, "consensus"))} for ceiling in ODDS_CEILINGS]
    viable = [item for item in iterations if item["calibration"]["candidates"] >= 100]
    chosen = max(viable, key=lambda item: (item["calibration"]["top3_rate"], item["calibration"]["win_rate"], -item["odds_ceiling"])) if viable else None
    result = {
        "theory": "market_consensus_axis_v1",
        "mechanism": "市場1番人気と履歴モデル1位が一致する馬は、二つの事前情報が整合した軸候補である",
        "selection_protocol": "calibrationで8個の事前固定オッズ上限から候補100件以上・3着内率最大を選び、externalでは固定",
        "baselines_external": {"market_favorite": metrics(selections(external, None, "market")), "model_top": metrics(selections(external, None, "model"))},
        "iterations": iterations,
        "chosen": chosen,
        "external": metrics(selections(external, chosen["odds_ceiling"], "consensus")) if chosen else None,
        "status": "accuracy_candidate" if chosen else "insufficient_calibration_sample",
        "warning": "Accuracy theory only. It does not imply positive expected value or a betting recommendation.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "market-consensus-axis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (OUTPUT / "market-consensus-axis.md").write_text("\n".join(("# 市場合意軸の外部精度評価", "", f"- 外部市場1番人気: {result['baselines_external']['market_favorite']}", f"- 選択条件: {result['chosen']}", f"- 外部結果: {result['external']}", f"- 注意: {result['warning']}", "")), encoding="utf-8", newline="\r\n")
    print(f"AXIS_ACCURACY_STATUS={result['status']}")


if __name__ == "__main__":
    main()
