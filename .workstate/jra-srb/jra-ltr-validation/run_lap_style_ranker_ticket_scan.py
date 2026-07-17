from __future__ import annotations

from collections import defaultdict
import gzip
import json
from pathlib import Path
import sqlite3


ROOT = Path(".workstate/jra-srb/jra-ltr-validation/lap-style-v1")
OUTPUT = Path(".workstate/jra-srb/jra-ltr-validation/lap-style-v1")
MARGINS = (0.0, 0.1, 0.2, 0.3, 0.5, 0.8)
SHAPES = ("wide_2", "wide_3", "wide_4", "quinella_2", "quinella_3", "quinella_4", "trio_23", "trio_24", "trio_34", "trio_box")


def key(numbers: list[str]) -> str:
    return "-".join(sorted(numbers, key=int))


def payouts() -> dict[tuple[str, str, str], int]:
    with sqlite3.connect("data/db/analysis.sqlite") as connection:
        rows = connection.execute("select race_id,bet_type,combination,max(payout) from payouts where bet_type in ('ワイド','馬連','3連複') group by race_id,bet_type,combination").fetchall()
    return {(race_id, bet_type, combination): int(value) for race_id, bet_type, combination, value in rows}


def load() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(ROOT / "ranker-predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            grouped[row["race_id"]].append(row)
    return grouped


def ticket_values(runners: list[dict], store: dict[tuple[str, str, str], int]) -> dict[str, list[int]]:
    ranked = sorted(runners, key=lambda row: row["ranker_rank"])
    if len(ranked) < 4:
        return {}
    race_id = ranked[0]["race_id"]
    a, b, c, d = [row["horse_no"] for row in ranked[:4]]
    def payout(kind: str, numbers: list[str]) -> int:
        return store.get((race_id, kind, key(numbers)), 0)
    return {"wide_2":[payout("ワイド",[a,b])],"wide_3":[payout("ワイド",[a,c])],"wide_4":[payout("ワイド",[a,d])],"quinella_2":[payout("馬連",[a,b])],"quinella_3":[payout("馬連",[a,c])],"quinella_4":[payout("馬連",[a,d])],"trio_23":[payout("3連複",[a,b,c])],"trio_24":[payout("3連複",[a,b,d])],"trio_34":[payout("3連複",[a,c,d])],"trio_box":[payout("3連複",[a,b,c]),payout("3連複",[a,b,d]),payout("3連複",[a,c,d])]}


def evaluate(races: dict[str, list[dict]], store: dict[tuple[str, str, str], int], dates: set[str], margin: float) -> dict[str, dict]:
    values: dict[str, list[int]] = defaultdict(list)
    candidates: dict[str, int] = defaultdict(int)
    for runners in races.values():
        if runners[0]["race_date"] not in dates:
            continue
        ranked = sorted(runners, key=lambda row: row["ranker_rank"])
        if len(ranked) < 2 or ranked[0]["ranker_score"] - ranked[1]["ranker_score"] < margin:
            continue
        for shape, payouts in ticket_values(runners, store).items():
            candidates[shape] += 1
            values[shape].extend(payouts)
    result = {}
    for shape in SHAPES:
        items = values[shape]
        ordered = sorted(items, reverse=True)
        result[shape] = {"axis_races": candidates[shape], "tickets": len(items), "hits": sum(value > 0 for value in items), "roi": sum(items) / (100 * len(items)) if items else 0.0, "no_top3_roi": sum(ordered[3:]) / (100 * len(ordered[3:])) if len(ordered) > 3 else 0.0}
    return result


def main() -> None:
    races, store = load(), payouts()
    calibration_days = {runners[0]["race_date"] for runners in races.values() if runners[0]["race_date"] <= "2026-01-25"}
    external_days = {runners[0]["race_date"] for runners in races.values() if runners[0]["race_date"] >= "2026-01-31"}
    trials = []
    for margin in MARGINS:
        report = evaluate(races, store, calibration_days, margin)
        for shape, value in report.items():
            trials.append({"margin": margin, "shape": shape, "calibration": value})
    viable = [item for item in trials if item["calibration"]["tickets"] >= 100]
    chosen = max(viable, key=lambda item: (item["calibration"]["no_top3_roi"], item["calibration"]["roi"]))
    external = evaluate(races, store, external_days, chosen["margin"])
    result = {"theory": "lap_style_ranker_ticket_scan_v1", "protocol": "model rank 1 axis, rank 2-4 partners; six pre-fixed score margins and ten shapes; calibration selects by no_top3_roi, external remains fixed", "chosen": chosen, "external_chosen": external[chosen["shape"]], "external_all_shapes": external, "warning": "Exploratory. A result must be confirmed on a further untouched period before use."}
    (OUTPUT / "lap-style-ticket-scan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (OUTPUT / "lap-style-ticket-scan.md").write_text("\n".join(("# ラップ×脚質Ranker買い方探索", "", f"- 校正選択: {chosen}", f"- 外部結果: {external[chosen['shape']]}", "")), encoding="utf-8", newline="\r\n")
    print(f"LAP_STYLE_TICKET_STATUS=completed chosen={chosen['shape']} external_roi={external[chosen['shape']]['roi']:.3f}")


if __name__ == "__main__":
    main()
