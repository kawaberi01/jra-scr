from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


WORKSTATE = Path(".workstate/jra-srb/prediction-v1-validation")

SPLITS = {
    "wf1_2025_07": "v86_wf1_2025_07_races.json",
    "wf2_2025_08": "v86_wf2_2025_08_races.json",
    "wf3_2025_09": "v86_wf3_2025_09_races.json",
    "validation_2025Q4": "v86_v86_validation_races.json",
    "holdout_2026H1": "v86_holdout_races.json",
}

COURSE_NAMES = {
    "01": "sapporo",
    "02": "hakodate",
    "03": "fukushima",
    "04": "niigata",
    "05": "tokyo",
    "06": "nakayama",
    "07": "chukyo",
    "08": "kyoto",
    "09": "hanshin",
    "10": "kokura",
}

MAIN_CODES = {"05", "06", "08", "09"}
LOCAL_CODES = {"01", "02", "03", "04", "10"}
CHUKYO_CODES = {"07"}


def venue_group(course_code: str | None) -> str:
    code = str(course_code or "")
    if code in MAIN_CODES:
        return "main"
    if code in LOCAL_CODES:
        return "local"
    if code in CHUKYO_CODES:
        return "chukyo"
    return "unknown"


def empty_stats() -> dict[str, Any]:
    return {
        "candidate_races": 0,
        "evaluated_races": 0,
        "excluded_races": 0,
        "bet_races": 0,
        "tickets": 0,
        "hits": 0,
        "total_bet": 0,
        "total_payout": 0,
        "payouts": [],
        "courses": defaultdict(lambda: {"candidate_races": 0, "bet_races": 0, "tickets": 0}),
    }


def add_race(stats: dict[str, Any], race: dict[str, Any]) -> None:
    code = str(race.get("course_code") or "unknown")
    stats["candidate_races"] += 1
    stats["courses"][code]["candidate_races"] += 1

    if race.get("status") == "evaluated":
        stats["evaluated_races"] += 1
    elif race.get("status") == "excluded":
        stats["excluded_races"] += 1

    tickets = race.get("tickets") or []
    hit_tickets = race.get("hit_tickets") or []
    payouts = [int(value or 0) for value in (race.get("payouts") or []) if int(value or 0) > 0]
    bet = int(race.get("bet") or 0)
    payout = int(race.get("payout") or 0)

    if tickets:
        stats["bet_races"] += 1
        stats["courses"][code]["bet_races"] += 1
        stats["courses"][code]["tickets"] += len(tickets)
    stats["tickets"] += len(tickets)
    stats["hits"] += len(hit_tickets)
    stats["total_bet"] += bet
    stats["total_payout"] += payout
    stats["payouts"].extend(payouts)


def finalize(stats: dict[str, Any]) -> dict[str, Any]:
    payouts = sorted(stats.pop("payouts"), reverse=True)
    total_bet = stats["total_bet"]
    total_payout = stats["total_payout"]
    without_max = total_payout - (payouts[0] if payouts else 0)
    without_top3 = total_payout - sum(payouts[:3])
    courses = stats.pop("courses")
    return {
        **stats,
        "return_rate": round(total_payout / total_bet, 4) if total_bet else None,
        "return_rate_without_max_payout": round(without_max / total_bet, 4) if total_bet else None,
        "return_rate_without_top3_payouts": round(without_top3 / total_bet, 4) if total_bet else None,
        "wide_hit_rate": round(stats["hits"] / stats["tickets"], 4) if stats["tickets"] else None,
        "max_payout": payouts[0] if payouts else 0,
        "courses": {
            COURSE_NAMES.get(code, code): values
            for code, values in sorted(courses.items())
        },
    }


def main() -> None:
    result: dict[str, Any] = {
        "theory_version": "v86",
        "groups": {
            "main": {"course_codes": sorted(MAIN_CODES), "courses": ["tokyo", "nakayama", "kyoto", "hanshin"]},
            "local": {"course_codes": sorted(LOCAL_CODES), "courses": ["sapporo", "hakodate", "fukushima", "niigata", "kokura"]},
            "chukyo": {"course_codes": sorted(CHUKYO_CODES), "courses": ["chukyo"]},
        },
        "splits": {},
        "combined": {},
    }

    combined = defaultdict(empty_stats)
    for split, filename in SPLITS.items():
        path = WORKSTATE / filename
        races = json.loads(path.read_text(encoding="utf-8"))
        split_stats = defaultdict(empty_stats)
        for race in races:
            group = venue_group(race.get("course_code"))
            add_race(split_stats[group], race)
            add_race(combined[group], race)
        result["splits"][split] = {group: finalize(stats) for group, stats in sorted(split_stats.items())}

    result["combined"] = {group: finalize(stats) for group, stats in sorted(combined.items())}

    json_path = WORKSTATE / "v86_venue_group_summary.json"
    md_path = WORKSTATE / "v86_venue_group_summary.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# v86 Venue Group Summary",
        "",
        "Groups:",
        "",
        "- main: tokyo / nakayama / kyoto / hanshin",
        "- local: sapporo / hakodate / fukushima / niigata / kokura",
        "- chukyo: chukyo",
        "",
        "## Combined",
        "",
        "| group | candidate | evaluated | bet_races | tickets | hits | ROI | no-max ROI | no-top3 ROI | max_payout |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group, stats in result["combined"].items():
        lines.append(
            f"| {group} | {stats['candidate_races']} | {stats['evaluated_races']} | "
            f"{stats['bet_races']} | {stats['tickets']} | {stats['hits']} | "
            f"{stats['return_rate']} | {stats['return_rate_without_max_payout']} | "
            f"{stats['return_rate_without_top3_payouts']} | {stats['max_payout']} |"
        )

    lines.extend(["", "## By Split", ""])
    for split, split_stats in result["splits"].items():
        lines.extend([
            f"### {split}",
            "",
            "| group | candidate | evaluated | bet_races | tickets | hits | ROI | no-max ROI | no-top3 ROI | max_payout |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for group, stats in split_stats.items():
            lines.append(
                f"| {group} | {stats['candidate_races']} | {stats['evaluated_races']} | "
                f"{stats['bet_races']} | {stats['tickets']} | {stats['hits']} | "
                f"{stats['return_rate']} | {stats['return_rate_without_max_payout']} | "
                f"{stats['return_rate_without_top3_payouts']} | {stats['max_payout']} |"
            )
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
