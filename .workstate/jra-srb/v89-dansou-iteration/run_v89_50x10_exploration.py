from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path


RANK_LIMITS = (1, 2, 3, 4, 5)
ODDS_MINS = (0.0, 2.0, 2.5, 3.0, 4.0)
ODDS_MAXES = (4.0, 6.0)
ITERATIONS = (
    ("all", ("05", "06", "08", "09"), 1, 8),
    ("early", ("05", "06", "08", "09"), 1, 4),
    ("late", ("05", "06", "08", "09"), 5, 8),
    ("r1_to_6", ("05", "06", "08", "09"), 1, 6),
    ("r3_to_8", ("05", "06", "08", "09"), 3, 8),
    ("tokyo_nakayama", ("05", "06"), 1, 8),
    ("kyoto_hanshin", ("08", "09"), 1, 8),
    ("tokyo_kyoto", ("05", "08"), 1, 8),
    ("nakayama_hanshin", ("06", "09"), 1, 8),
    ("middle_r3_to_6", ("05", "06", "08", "09"), 3, 6),
)
MIN_TICKETS = {"validation": 6, "known_holdout": 20}


def gate(row: dict, theory: dict, iteration: tuple) -> bool:
    _, courses, race_no_min, race_no_max = iteration
    odds = float(row.get("axis_odds") or 0)
    return bool(
        row.get("bet")
        and (row.get("axis_rank") or 999) <= theory["axis_rank_max"]
        and theory["axis_odds_min"] <= odds <= theory["axis_odds_max"]
        and row.get("course_code") in courses
        and race_no_min <= int(row.get("race_no") or 0) <= race_no_max
    )


def metrics(rows: list[dict], theory: dict, iteration: tuple) -> dict:
    payouts = [payout for row in rows if gate(row, theory, iteration) for payout in (row.get("payouts") or [])]
    ordered = sorted(payouts, reverse=True)
    def roi(values: list[int]) -> float:
        return sum(values) / (100 * len(values)) if values else 0.0
    return {"tickets": len(payouts), "hits": sum(value > 0 for value in payouts), "roi": roi(payouts), "no_max_roi": roi(ordered[1:]), "no_top3_roi": roi(ordered[3:])}


def passes(values: dict[str, dict]) -> bool:
    return all(
        value["tickets"] >= MIN_TICKETS[period]
        and value["roi"] >= 1.0
        and value["no_max_roi"] >= 1.0
        and value["no_top3_roi"] >= 1.0
        for period, value in values.items()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 50 V89 gate theories with 10 bounded exploratory iterations each.")
    parser.add_argument("--input-dir", type=Path, default=Path(".workstate/jra-srb/prediction-v1-validation"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/v89-dansou-iteration"))
    args = parser.parse_args()
    periods = {
        "validation": json.loads((args.input_dir / "v89_validation_races.json").read_text(encoding="utf-8")),
        "known_holdout": json.loads((args.input_dir / "v89_holdout_races.json").read_text(encoding="utf-8")),
    }
    theories = [
        {"theory_id": f"v89g{index:02d}", "axis_rank_max": rank, "axis_odds_min": odds_min, "axis_odds_max": odds_max}
        for index, (rank, odds_min, odds_max) in enumerate(product(RANK_LIMITS, ODDS_MINS, ODDS_MAXES), 1)
    ]
    runs = []
    for theory in theories:
        for iteration_number, iteration in enumerate(ITERATIONS, 1):
            values = {period: metrics(rows, theory, iteration) for period, rows in periods.items()}
            runs.append({"theory": theory, "iteration": iteration_number, "iteration_name": iteration[0], "metrics": values, "passed": passes(values)})
    candidates = [run for run in runs if run["passed"]]
    candidates.sort(key=lambda run: (-run["metrics"]["known_holdout"]["no_top3_roi"], -run["metrics"]["validation"]["no_top3_roi"], -run["metrics"]["known_holdout"]["tickets"]))
    result = {
        "status": "exploratory_only",
        "warning": "既知validation/holdout上の500比較であり、複数比較・過適合リスクが高い。購入採用・昇格は禁止。",
        "theory_count": len(theories), "iterations_per_theory": len(ITERATIONS), "total_runs": len(runs),
        "selection_criteria": {"minimum_tickets": MIN_TICKETS, "minimum_roi": 1.0, "minimum_no_max_roi": 1.0, "minimum_no_top3_roi": 1.0},
        "candidates": candidates, "runs": runs,
        "next_step": "候補を一つだけ事前固定し、新しい未使用期間で一回だけ評価する",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "v89-50x10-exploration.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = ["# V89 派生ゲート 50理論 × 10反復 探索", "", "- 状態: exploratory_only", "- 既知期間に対する500比較。購入採用・昇格は禁止。", f"- 条件通過候補: {len(candidates)}件", "", "| 理論 | 反復 | validation 点数 / ROI / no-top3 | holdout 点数 / ROI / no-top3 |", "| --- | --- | --- | --- |"]
    for run in candidates[:20]:
        validation = run["metrics"]["validation"]
        holdout = run["metrics"]["known_holdout"]
        report.append(f"| {run['theory']['theory_id']} (rank≤{run['theory']['axis_rank_max']}, odds {run['theory']['axis_odds_min']:.1f}〜{run['theory']['axis_odds_max']:.1f}) | {run['iteration_name']} | {validation['tickets']} / {validation['roi']:.3f} / {validation['no_top3_roi']:.3f} | {holdout['tickets']} / {holdout['roi']:.3f} / {holdout['no_top3_roi']:.3f} |")
    (args.output_dir / "v89-50x10-exploration.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    print(f"EXPLORATION_STATUS=completed candidates={len(candidates)}")


if __name__ == "__main__":
    main()
