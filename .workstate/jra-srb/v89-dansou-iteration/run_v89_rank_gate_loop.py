from __future__ import annotations

import argparse
import json
from pathlib import Path


MAX_ITERATIONS = 50
MIN_TICKETS = {"validation": 6, "known_holdout": 20}


def metrics(rows: list[dict], rank_limit: int) -> dict:
    payouts = [
        payout
        for row in rows
        if row.get("bet") and (row.get("axis_rank") or 999) <= rank_limit
        for payout in (row.get("payouts") or [])
    ]
    ordered = sorted(payouts, reverse=True)
    def roi(values: list[int]) -> float:
        return sum(values) / (100 * len(values)) if values else 0.0
    return {
        "tickets": len(payouts), "hits": sum(value > 0 for value in payouts),
        "roi": roi(payouts), "no_max_roi": roi(ordered[1:]), "no_top3_roi": roi(ordered[3:]),
    }


def is_good(values: dict[str, dict]) -> bool:
    return all(
        values[period]["tickets"] >= MIN_TICKETS[period]
        and values[period]["roi"] >= 1.0
        and values[period]["no_max_roi"] >= 1.0
        and values[period]["no_top3_roi"] >= 1.0
        for period in MIN_TICKETS
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded pure-V89 axis rank gate exploration.")
    parser.add_argument("--input-dir", type=Path, default=Path(".workstate/jra-srb/prediction-v1-validation"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/v89-dansou-iteration"))
    args = parser.parse_args()
    periods = {
        "validation": json.loads((args.input_dir / "v89_validation_races.json").read_text(encoding="utf-8")),
        "known_holdout": json.loads((args.input_dir / "v89_holdout_races.json").read_text(encoding="utf-8")),
    }
    iterations = []
    selected = None
    for iteration, rank_limit in enumerate(range(1, 6), 1):
        if iteration > MAX_ITERATIONS:
            break
        values = {period: metrics(rows, rank_limit) for period, rows in periods.items()}
        passed = is_good(values)
        entry = {
            "iteration": iteration,
            "hypothesis": f"V89の文脈補正後の軸を、基礎スコア順位{rank_limit}位以内に限定する",
            "rank_limit": rank_limit,
            "metrics": values,
            "passed": passed,
        }
        iterations.append(entry)
        if passed:
            selected = entry
            break
    result = {
        "status": "exploratory_passed" if selected else "exploratory_no_candidate",
        "maximum_iterations": MAX_ITERATIONS,
        "executed_iterations": len(iterations),
        "selection_criteria": {"minimum_tickets": MIN_TICKETS, "minimum_roi": 1.0, "minimum_no_max_roi": 1.0, "minimum_no_top3_roi": 1.0},
        "selected": selected,
        "iterations": iterations,
        "promotion": "forbidden: this search uses known validation/holdout data; evaluate the selected gate once on a fresh unused period",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "v89-rank-gate-loop.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = ["# V89 軸基礎順位ゲート探索", "", f"- 状態: `{result['status']}`", f"- 上限: {MAX_ITERATIONS}回 / 実行: {len(iterations)}回", "- 既知データ探索のため、採用・昇格には使わない。", "", "| 回 | 軸基礎順位上限 | validation 点数 / ROI / no-top3 | holdout 点数 / ROI / no-top3 | 判定 |", "| ---: | ---: | --- | --- | --- |"]
    for entry in iterations:
        validation = entry["metrics"]["validation"]
        holdout = entry["metrics"]["known_holdout"]
        report.append(f"| {entry['iteration']} | {entry['rank_limit']} | {validation['tickets']} / {validation['roi']:.3f} / {validation['no_top3_roi']:.3f} | {holdout['tickets']} / {holdout['roi']:.3f} / {holdout['no_top3_roi']:.3f} | {'pass' if entry['passed'] else 'continue'} |")
    (args.output_dir / "v89-rank-gate-loop.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    print(f"ITERATION_STATUS={result['status']}")


if __name__ == "__main__":
    main()
