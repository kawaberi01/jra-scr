from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3


HYPOTHESES = {
    "baseline": "V89の既存買い目をそのまま集計する対照群",
    "axis_above_max_gap": "V89軸が最大断層の直上かつ単勝3.0〜10.9倍のときだけ、既存V89買い目を採用する",
    "middle_above_max_gap": "V89相手が最大断層の直上かつ単勝3.0〜10.9倍のときだけ、そのワイド点を採用する",
    "either_above_max_gap": "V89軸または相手が最大断層の直上かつ単勝3.0〜10.9倍のときだけ、そのワイド点を採用する",
}


def load_odds(db_path: Path) -> dict[str, dict[str, float]]:
    with sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            """
            select m.jra_race_id, ne.horse_no, ne.win_odds
            from netkeiba_race_mappings m
            join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id
            where ne.win_odds > 0
            """
        ).fetchall()
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for race_id, horse_no, odds in rows:
        result[str(race_id)][str(horse_no)] = float(odds)
    return result


def dansou_context(odds_by_horse: dict[str, float]) -> dict | None:
    ranked = sorted(odds_by_horse.items(), key=lambda item: (item[1], int(item[0]) if item[0].isdigit() else 999))[:6]
    if len(ranked) < 6:
        return None
    gaps = [ranked[index + 1][1] / ranked[index][1] for index in range(5)]
    max_index = max(range(5), key=lambda index: gaps[index])
    max_gap = gaps[max_index]
    if max_gap < 2.0:
        return {"ranked": ranked, "gaps": gaps, "max_gap": max_gap, "candidate": None, "pattern": "no_gap"}
    candidate = ranked[max_index][0]
    pattern = "p1" if max_index == 0 and max_gap >= 2.5 else "p2" if max_index == 1 else "p3" if max_index >= 2 else "other"
    if sum(gap >= 2.0 for gap in gaps) >= 2:
        pattern = "p4"
    return {"ranked": ranked, "gaps": gaps, "max_gap": max_gap, "candidate": candidate, "pattern": pattern}


def selected_tickets(row: dict, context: dict | None, hypothesis: str) -> list[tuple[str, int]]:
    tickets = list(zip(row.get("tickets") or [], row.get("payouts") or []))
    if hypothesis == "baseline":
        return tickets
    if context is None or context["candidate"] is None:
        return []
    candidate = context["candidate"]
    odds = dict(context["ranked"])
    in_value_band = 3.0 <= odds[candidate] <= 10.9
    if not in_value_band:
        return []
    axis = str(row.get("axis_no") or "")
    if hypothesis == "axis_above_max_gap":
        return tickets if axis == candidate else []
    selected = []
    for ticket, payout in tickets:
        horse_numbers = ticket.split("-")
        middle = next((number for number in horse_numbers if number != axis), "")
        if hypothesis == "middle_above_max_gap" and middle == candidate:
            selected.append((ticket, payout))
        if hypothesis == "either_above_max_gap" and (axis == candidate or middle == candidate):
            selected.append((ticket, payout))
    return selected


def metrics(entries: list[dict]) -> dict:
    payouts = [entry["payout"] for entry in entries]
    stake = 100 * len(entries)
    def roi(values: list[int]) -> float:
        return sum(values) / (100 * len(values)) if values else 0.0
    sorted_payouts = sorted(payouts, reverse=True)
    return {
        "tickets": len(entries),
        "hits": sum(value > 0 for value in payouts),
        "hit_rate": sum(value > 0 for value in payouts) / len(entries) if entries else 0.0,
        "stake": stake,
        "payout": sum(payouts),
        "roi": roi(payouts),
        "no_max_roi": roi(sorted_payouts[1:]),
        "no_top3_roi": roi(sorted_payouts[3:]),
        "max_payout_share": max(payouts) / sum(payouts) if sum(payouts) else 0.0,
        "patterns": {name: sum(entry["pattern"] == name for entry in entries) for name in ("p1", "p2", "p3", "p4")},
    }


def evaluate(rows: list[dict], odds: dict[str, dict[str, float]], hypothesis: str) -> dict:
    entries = []
    missing_odds = 0
    for row in rows:
        if not row.get("bet"):
            continue
        context = dansou_context(odds.get(str(row["jra_race_id"]), {}))
        if context is None:
            missing_odds += 1
            continue
        for ticket, payout in selected_tickets(row, context, hypothesis):
            entries.append({"race_id": row["jra_race_id"], "ticket": ticket, "payout": int(payout), "pattern": context["pattern"], "max_gap": context["max_gap"]})
    return {"hypothesis": hypothesis, "definition": HYPOTHESES[hypothesis], "metrics": metrics(entries), "missing_odds_bet_races": missing_odds, "entries": entries}


def main() -> None:
    parser = argparse.ArgumentParser(description="Exploratory V89 odds-dansou gate iteration.")
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--input-dir", type=Path, default=Path(".workstate/jra-srb/prediction-v1-validation"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/v89-dansou-iteration"))
    args = parser.parse_args()
    odds = load_odds(args.db)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = {"status": "exploratory_only", "reason": "V89の既知validation/holdoutを使うため採用根拠にはしない", "hypotheses": HYPOTHESES, "periods": {}}
    for label, filename in (("validation", "v89_validation_races.json"), ("known_holdout", "v89_holdout_races.json")):
        rows = json.loads((args.input_dir / filename).read_text(encoding="utf-8"))
        result["periods"][label] = {name: evaluate(rows, odds, name) for name in HYPOTHESES}
    (args.output_dir / "v89-dansou-iteration.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = ["# V89 オッズ断層ゲート探索", "", "- 状態: exploratory_only", "- 既知validation/holdoutを使うため、採用・昇格の根拠にはしない。", ""]
    for period, values in result["periods"].items():
        report.extend((f"## {period}", "", "| 仮説 | 点数 | ROI | no-max ROI | no-top3 ROI |", "| --- | ---: | ---: | ---: | ---: |"))
        for name, value in values.items():
            data = value["metrics"]
            report.append(f"| {name} | {data['tickets']} | {data['roi']:.3f} | {data['no_max_roi']:.3f} | {data['no_top3_roi']:.3f} |")
        report.append("")
    (args.output_dir / "v89-dansou-iteration.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    print("ITERATION_STATUS=exploratory_only")


if __name__ == "__main__":
    main()
