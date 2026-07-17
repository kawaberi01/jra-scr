from __future__ import annotations

from collections import defaultdict
import gzip
import json
from pathlib import Path


ARTIFACTS = Path(".workstate/jra-srb/jra-win-ev-revalidation/artifacts-2024-2026")
OUTPUT = Path(".workstate/jra-srb/jra-axis-accuracy-validation")
MARGINS = (0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.06)


def load() -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    with gzip.open(ARTIFACTS / "runner-predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    races: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        races[row["race_id"]].append(row)
    return races, json.loads((ARTIFACTS / "split-metadata.json").read_text(encoding="utf-8"))["date_sets"]


def select(races: dict[str, list[dict]], days: set[str], margin: float) -> list[dict]:
    output = []
    for runners in races.values():
        if runners[0]["race_date"] not in days:
            continue
        market = sorted(runners, key=lambda item: (item["win_odds"], int(item["horse_no"])))
        model = sorted(runners, key=lambda item: (-item["raw_win_probability"], int(item["horse_no"])))
        candidate = model[0]
        market_rank = next(index for index, item in enumerate(market, 1) if item["horse_no"] == candidate["horse_no"])
        lead = candidate["raw_win_probability"] - model[1]["raw_win_probability"]
        if 3 <= market_rank <= 6 and 3.0 <= candidate["win_odds"] <= 15.0 and lead >= margin:
            output.append(candidate)
    return output


def metrics(rows: list[dict]) -> dict:
    returns = [row["win_payout"] if row["label_win"] else 0 for row in rows]
    return {"candidates": len(rows), "win_rate": sum(row["label_win"] for row in rows) / len(rows) if rows else 0.0, "top3_rate": sum(row["label_top3"] for row in rows) / len(rows) if rows else 0.0, "roi": sum(returns) / (100 * len(rows)) if rows else 0.0, "mean_odds": sum(row["win_odds"] for row in rows) / len(rows) if rows else 0.0}


def main() -> None:
    races, split = load()
    calibration_days, external_days = set(split["calibration"]), set(split["external"])
    iterations = [{"model_lead_margin": value, "calibration": metrics(select(races, calibration_days, value))} for value in MARGINS]
    viable = [item for item in iterations if item["calibration"]["candidates"] >= 100]
    chosen = max(viable, key=lambda item: (item["calibration"]["top3_rate"], item["calibration"]["win_rate"], item["calibration"]["roi"])) if viable else None
    result = {"theory": "market_disagreement_axis_v1", "mechanism": "市場3〜6番人気だが履歴モデル1位の馬は、市場が過小評価した構造情報を持つ軸候補である", "selection_protocol": "10個の事前固定モデル先頭差から校正候補100件以上・3着内率最大を選び、externalでは固定", "iterations": iterations, "chosen": chosen, "external": metrics(select(races, external_days, chosen["model_lead_margin"])) if chosen else None, "warning": "A non-favorite accuracy experiment; positive ROI is not assumed or promoted without a further untouched period."}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "market-disagreement-axis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (OUTPUT / "market-disagreement-axis.md").write_text("\n".join(("# 市場不一致軸の外部精度評価", "", f"- 条件: {result['chosen']}", f"- 外部結果: {result['external']}", "")), encoding="utf-8", newline="\r\n")
    print("DISAGREEMENT_AXIS_STATUS=completed")


if __name__ == "__main__":
    main()
