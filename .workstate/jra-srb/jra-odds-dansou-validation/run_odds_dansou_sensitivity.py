from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import product
import json
from pathlib import Path
import sqlite3


def select_candidate(runners: list[dict]) -> dict | None:
    ranked = sorted(runners, key=lambda item: (item["adjusted_odds"], int(item["horse_no"])))[:6]
    if len(ranked) < 6:
        return None
    gaps = [ranked[index + 1]["adjusted_odds"] / ranked[index]["adjusted_odds"] for index in range(5)]
    max_index = max(range(5), key=lambda index: gaps[index])
    candidate = ranked[max_index]
    if gaps[max_index] < 2 or not 3.0 <= candidate["adjusted_odds"] <= 10.9:
        return None
    return candidate


def metrics(selections: list[dict]) -> dict:
    payouts = [item["payout"] if item["rank"] == 1 and item["payout"] else 0 for item in selections]
    ordered = sorted(payouts, reverse=True)

    def roi(values: list[int]) -> float:
        return sum(values) / (100 * len(values)) if values else 0.0

    return {
        "selections": len(selections),
        "hits": sum(value > 0 for value in payouts),
        "roi": roi(payouts),
        "no_max_roi": roi(ordered[1:]),
        "no_top3_roi": roi(ordered[3:]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded ±odds sensitivity analysis for the original odds-dansou rule.")
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--delta", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-odds-dansou-validation"))
    args = parser.parse_args()
    with sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select r.race_id, r.race_date, re.horse_no, re.rank, ne.win_odds, p.payout
            from races r join result_entries re on re.race_id=r.race_id
            join netkeiba_race_mappings m on m.jra_race_id=r.race_id
            join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id and ne.horse_no=re.horse_no
            left join payouts p on p.race_id=r.race_id and p.bet_type in ('win','単勝') and p.combination=re.horse_no
            where length(r.race_id)=12 and substr(r.race_id,9,2) between '01' and '10'
              and r.source like 'https://www.jra.go.jp/%' and ne.win_odds>0
              and coalesce(r.race_name,'') not like '%新馬%' and coalesce(r.race_name,'') not like '%メイクデビュー%'
              and coalesce(r.race_name,'') not like '%障害%'
            order by r.race_date,r.race_id,cast(re.horse_no as integer)
            """
        ).fetchall()
    by_race: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        value = dict(row)
        value["adjusted_odds"] = float(value["win_odds"])
        by_race[str(row["race_id"])].append(value)

    central: list[dict] = []
    robust: list[dict] = []
    skipped = Counter()
    for runners in by_race.values():
        ranked = sorted(runners, key=lambda item: (item["win_odds"], int(item["horse_no"])))
        candidate = select_candidate(ranked)
        if candidate is None:
            skipped["central_rule_not_selected"] += 1
            continue
        central.append(candidate)
        top6 = ranked[:6]
        if len(top6) < 6:
            skipped["fewer_than_six"] += 1
            continue
        if len(ranked) > 6 and ranked[6]["win_odds"] - args.delta <= top6[-1]["win_odds"] + args.delta:
            skipped["seventh_can_enter_top6"] += 1
            continue
        scenario_horses = set()
        for signs in product((-1, 1), repeat=6):
            scenario = [
                {**item, "adjusted_odds": max(0.1, float(item["win_odds"]) + sign * args.delta)}
                for item, sign in zip(top6, signs)
            ]
            selected = select_candidate(scenario)
            scenario_horses.add(str(selected["horse_no"]) if selected is not None else "none")
        if scenario_horses == {str(candidate["horse_no"])}:
            robust.append(candidate)
        else:
            skipped["top6_corner_scenarios_change_decision"] += 1

    result = {
        "status": "historical_proxy_only",
        "rule": "original GPTs top6 adjacent odds gap >=2.0; select directly above max gap; candidate odds 3.0..10.9",
        "uncertainty_model": {"per_horse_absolute_odds_delta": args.delta, "scenarios": 64, "robust_definition": "same selected horse under every top6 ±delta corner; seventh horse cannot enter top6"},
        "races_with_odds": len(by_race),
        "central_final_odds": metrics(central),
        "robust_under_delta": metrics(robust),
        "skipped": dict(skipped),
        "warning": "The ±0.5 assumption is a sensitivity model, not observed pre-race odds history. Results cannot alone promote a live betting rule.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "odds-dansou-sensitivity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (args.output_dir / "odds-dansou-sensitivity.md").write_text(
        "\n".join((
            "# 元Gpts オッズ断層 ±0.5感度分析", "",
            f"- 対象レース: {result['races_with_odds']}",
            f"- 確定オッズ中心: {result['central_final_odds']}",
            f"- ±{args.delta}で堅牢: {result['robust_under_delta']}",
            f"- 注意: {result['warning']}", "",
        )), encoding="utf-8", newline="\r\n"
    )
    print(f"DANSOU_SENSITIVITY_STATUS=completed robust={len(robust)} roi={result['robust_under_delta']['roi']:.3f}")


if __name__ == "__main__":
    main()
