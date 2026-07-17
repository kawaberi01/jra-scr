from __future__ import annotations

from collections import defaultdict
import gzip
import json
from pathlib import Path
import sqlite3


ARTIFACTS = Path(".workstate/jra-srb/jra-win-ev-revalidation/artifacts-2024-2026")
OUTPUT = Path(".workstate/jra-srb/jra-axis-accuracy-validation")


def key(numbers: list[str]) -> str:
    return "-".join(str(number) for number in sorted(numbers, key=int))


def load_axis_races() -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    with gzip.open(ARTIFACTS / "runner-predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    split = json.loads((ARTIFACTS / "split-metadata.json").read_text(encoding="utf-8"))["date_sets"]
    races: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        races[row["race_id"]].append(row)
    return races, split


def load_payouts() -> dict[tuple[str, str, str], int]:
    with sqlite3.connect("data/db/analysis.sqlite") as connection:
        rows = connection.execute(
            """
            select race_id, bet_type, combination, max(payout)
            from payouts
            where bet_type in ('ワイド', '馬連', '3連複')
            group by race_id, bet_type, combination
            """
        ).fetchall()
    return {(race_id, bet_type, combination): int(payout) for race_id, bet_type, combination, payout in rows}


def ticket_returns(runners: list[dict], payouts: dict[tuple[str, str, str], int]) -> dict[str, list[int]]:
    market = sorted(runners, key=lambda item: (item["win_odds"], int(item["horse_no"])))
    model = max(runners, key=lambda item: (item["raw_win_probability"], -int(item["horse_no"])))
    axis = market[0]
    if axis["horse_no"] != model["horse_no"] or axis["win_odds"] > 2.5 or len(market) < 4:
        return {}
    race_id = axis["race_id"]
    a, b, c, d = [item["horse_no"] for item in market[:4]]

    def payout(bet_type: str, numbers: list[str]) -> int:
        return payouts.get((race_id, bet_type, key(numbers)), 0)

    return {
        "wide_m2": [payout("ワイド", [a, b])],
        "wide_m3": [payout("ワイド", [a, c])],
        "wide_m4": [payout("ワイド", [a, d])],
        "quinella_m2": [payout("馬連", [a, b])],
        "quinella_m3": [payout("馬連", [a, c])],
        "quinella_m4": [payout("馬連", [a, d])],
        "trio_m2_m3": [payout("3連複", [a, b, c])],
        "trio_m2_m4": [payout("3連複", [a, b, d])],
        "trio_m3_m4": [payout("3連複", [a, c, d])],
        "trio_box_m2_m4": [payout("3連複", [a, b, c]), payout("3連複", [a, b, d]), payout("3連複", [a, c, d])],
    }


def evaluate(days: set[str], races: dict[str, list[dict]], payouts: dict[tuple[str, str, str], int]) -> dict[str, dict]:
    returns: dict[str, list[int]] = defaultdict(list)
    selected_races: dict[str, int] = defaultdict(int)
    for race_id, runners in races.items():
        if runners[0]["race_date"] not in days:
            continue
        tickets = ticket_returns(runners, payouts)
        for name, values in tickets.items():
            selected_races[name] += 1
            returns[name].extend(values)
    result = {}
    for name, values in returns.items():
        ordered = sorted(values, reverse=True)
        result[name] = {
            "axis_races": selected_races[name],
            "tickets": len(values),
            "hits": sum(value > 0 for value in values),
            "roi": sum(values) / (100 * len(values)) if values else 0.0,
            "no_max_roi": sum(ordered[1:]) / (100 * len(ordered[1:])) if len(ordered) > 1 else 0.0,
            "no_top3_roi": sum(ordered[3:]) / (100 * len(ordered[3:])) if len(ordered) > 3 else 0.0,
        }
    return result


def main() -> None:
    races, split = load_axis_races()
    payouts = load_payouts()
    calibration = evaluate(set(split["calibration"]), races, payouts)
    external = evaluate(set(split["external"]), races, payouts)
    viable = [name for name, value in calibration.items() if value["tickets"] >= 100]
    chosen = max(viable, key=lambda name: (calibration[name]["no_top3_roi"], calibration[name]["no_max_roi"], calibration[name]["roi"]))
    result = {
        "theory": "market_consensus_axis_v1_ticket_scan",
        "axis": "market favorite equals history-model top and odds <=2.5",
        "partner_space": "market ranks 2 through 4; ten pre-fixed ticket shapes",
        "selection_protocol": "choose one shape on calibration by no_top3_roi, then report unchanged external metrics",
        "calibration": calibration,
        "chosen_ticket_shape": chosen,
        "external": external,
        "external_chosen": external[chosen],
        "warning": "Exploratory ticket scan. A positive external result still requires a new untouched period before betting use.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "market-consensus-ticket-scan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (OUTPUT / "market-consensus-ticket-scan.md").write_text("\n".join(("# 市場合意軸の買い方探索", "", f"- 校正選択: {chosen}", f"- 外部結果: {external[chosen]}", f"- 注意: {result['warning']}", "")), encoding="utf-8", newline="\r\n")
    print(f"TICKET_SCAN_STATUS=completed chosen={chosen} external_roi={external[chosen]['roi']:.3f}")


if __name__ == "__main__":
    main()
