from __future__ import annotations

import argparse
import json
from pathlib import Path


HYPOTHESES = {
    "baseline": "既存V89の対照群",
    "axis_base_rank_le_3": "文脈補正後の軸が、基礎スコア順位でも3位以内のときだけ採用する",
    "axis_odds_2_5_to_10": "軸単勝が2.5〜10.0倍のときだけ採用する",
    "axis_base_rank_le_3_and_odds_2_5_to_10": "基礎スコア順位3位以内かつ軸単勝2.5〜10.0倍のときだけ採用する",
}


def allowed(row: dict, hypothesis: str) -> bool:
    if hypothesis == "baseline":
        return True
    rank_ok = (row.get("axis_rank") or 999) <= 3
    odds = float(row.get("axis_odds") or 0)
    odds_ok = 2.5 <= odds <= 10.0
    return rank_ok if hypothesis == "axis_base_rank_le_3" else odds_ok if hypothesis == "axis_odds_2_5_to_10" else rank_ok and odds_ok


def metrics(rows: list[dict], hypothesis: str) -> dict:
    entries = [payout for row in rows if row.get("bet") and allowed(row, hypothesis) for payout in (row.get("payouts") or [])]
    ordered = sorted(entries, reverse=True)
    def roi(values: list[int]) -> float:
        return sum(values) / (100 * len(values)) if values else 0.0
    return {
        "tickets": len(entries), "hits": sum(value > 0 for value in entries),
        "roi": roi(entries), "no_max_roi": roi(ordered[1:]), "no_top3_roi": roi(ordered[3:]),
        "max_payout_share": max(entries) / sum(entries) if sum(entries) else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Exploratory pure-V89 hypothesis iteration.")
    parser.add_argument("--input-dir", type=Path, default=Path(".workstate/jra-srb/prediction-v1-validation"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/v89-dansou-iteration"))
    args = parser.parse_args()
    result = {"status": "exploratory_only", "reason": "既知V89 validation/holdoutを使うため採用根拠にはしない", "hypotheses": HYPOTHESES, "periods": {}}
    for label, filename in (("validation", "v89_validation_races.json"), ("known_holdout", "v89_holdout_races.json")):
        rows = json.loads((args.input_dir / filename).read_text(encoding="utf-8"))
        result["periods"][label] = {name: metrics(rows, name) for name in HYPOTHESES}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "v89-pure-iteration.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = ["# V89 単独仮説探索", "", "- 状態: exploratory_only", "- 既知validation/holdoutを使うため、採用・昇格の根拠にはしない。", ""]
    for period, values in result["periods"].items():
        report.extend((f"## {period}", "", "| 仮説 | 点数 | ROI | no-max ROI | no-top3 ROI |", "| --- | ---: | ---: | ---: | ---: |"))
        for name, value in values.items():
            report.append(f"| {name} | {value['tickets']} | {value['roi']:.3f} | {value['no_max_roi']:.3f} | {value['no_top3_roi']:.3f} |")
        report.append("")
    (args.output_dir / "v89-pure-iteration.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    print("ITERATION_STATUS=exploratory_only")


if __name__ == "__main__":
    main()
