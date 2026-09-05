from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


COURSES = {"05": "tokyo", "06": "nakayama"}
PERIODS = {
    "known_validation": "v89_validation_races.json",
    "known_holdout": "v89_holdout_races.json",
}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    tickets = [ticket for row in evaluated for ticket in row.get("tickets", [])]
    hits = [ticket for row in evaluated for ticket in row.get("hit_tickets", [])]
    payouts = [value for row in evaluated for value in row.get("payouts", []) if value > 0]
    total_bet = sum(int(row.get("bet") or 0) for row in evaluated)
    total_payout = sum(int(row.get("payout") or 0) for row in evaluated)
    return {
        "candidate_races": len(rows),
        "evaluated_races": len(evaluated),
        "tickets": len(tickets),
        "hits": len(hits),
        "total_bet": total_bet,
        "total_payout": total_payout,
        "roi": round(total_payout / total_bet, 4) if total_bet else None,
        "roi_without_max": round((total_payout - max(payouts, default=0)) / total_bet, 4) if total_bet else None,
        "roi_without_top3": round((total_payout - sum(sorted(payouts, reverse=True)[:3])) / total_bet, 4) if total_bet else None,
        "axis_top3_rate": round(sum(bool(row.get("axis_top3")) for row in evaluated) / len(evaluated), 4) if evaluated else None,
        "partner_top3_rate": round(sum(int(row.get("middle_top3_count") or 0) for row in evaluated if row.get("tickets")) / len(tickets), 4) if tickets else None,
        "hit_rate": round(len(hits) / len(tickets), 4) if tickets else None,
        "ticket_target_rate": round(len(tickets) / len(evaluated), 4) if evaluated else None,
        "max_payout": max(payouts, default=0),
    }


def race_meta(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        select r.race_id, r.surface, r.distance, r.race_no, r.race_name, count(ru.horse_no) as field_size
        from races r left join runners ru on ru.race_id = r.race_id
        where r.source like 'https://www.jra.go.jp/%'
        group by r.race_id
        """
    ).fetchall()
    return {str(row[0]): dict(row) for row in rows}


def segment_key(meta: dict[str, Any], kind: str) -> str:
    if kind == "surface":
        return "dirt" if "ダート" in str(meta.get("surface") or "") else "turf" if "芝" in str(meta.get("surface") or "") else "other"
    if kind == "distance":
        digits = "".join(char for char in str(meta.get("distance") or "") if char.isdigit())
        distance = int(digits) if digits else 0
        return "sprint_1400_or_less" if distance <= 1400 else "mile_1401_1800" if distance <= 1800 else "middle_1801_2200" if distance <= 2200 else "long_over_2200"
    if kind == "field_size":
        size = int(meta.get("field_size") or 0)
        return "le_10" if size <= 10 else "11_13" if size <= 13 else "ge_14"
    if kind == "race_no":
        number = int(meta.get("race_no") or 0)
        return "1_4" if number <= 4 else "5_8" if number <= 8 else "9_12"
    name = str(meta.get("race_name") or "")
    surface = str(meta.get("surface") or "")
    if "障害" in name or "障" in surface:
        return "obstacle"
    if "新馬" in name or "メイクデビュー" in name:
        return "newcomer"
    return "flat_general"


def popularity_baseline(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        select substr(r.race_id, 9, 2) as course_code, re.jra_race_id,
               min(case when cast(re.popularity as integer) = 1 then cast(re.rank as integer) end) as favorite_rank
        from races r join netkeiba_result_entries re on re.jra_race_id = r.race_id
        where r.source like 'https://www.jra.go.jp/%'
          and substr(r.race_id, 9, 2) in ('05', '06')
          and r.race_date between ? and ?
        group by substr(r.race_id, 9, 2), re.jra_race_id
        """,
        (start, end),
    ).fetchall()
    result = {}
    for code, name in COURSES.items():
        selected = [row for row in rows if row[0] == code and row[2] is not None]
        result[name] = {
            "races": len(selected),
            "top3_rate": round(sum(int(row[2]) <= 3 for row in selected) / len(selected), 4) if selected else None,
        }
    all_rows = [row for row in rows if row[2] is not None]
    result["combined"] = {
        "races": len(all_rows),
        "top3_rate": round(sum(int(row[2]) <= 3 for row in all_rows) / len(all_rows), 4) if all_rows else None,
    }
    return result


def build(db: Path, source_dir: Path, history_artifact: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        metadata = race_meta(conn)
        output: dict[str, Any] = {
            "status": "diagnostic_only",
            "reason": "No historical pre-race odds snapshots; these results cannot promote the model.",
            "v89": {},
            "simple_popularity_baseline": {},
        }
        date_ranges = {
            "known_validation": ("2025-10-01", "2025-12-31"),
            "known_holdout": ("2026-01-01", "2026-06-28"),
        }
        for period, filename in PERIODS.items():
            rows = json.loads((source_dir / filename).read_text(encoding="utf-8"))
            target = [row for row in rows if row.get("course_code") in COURSES]
            period_result = {
                "combined": summarize(target),
                "by_course": {
                    name: summarize([row for row in target if row.get("course_code") == code])
                    for code, name in COURSES.items()
                },
                "segments": {},
            }
            for kind in ("surface", "distance", "field_size", "race_no", "class"):
                groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in target:
                    meta = metadata.get(str(row["jra_race_id"]), {})
                    groups[segment_key(meta, kind)].append(row)
                period_result["segments"][kind] = {key: summarize(value) for key, value in sorted(groups.items())}
            output["v89"][period] = period_result
            output["simple_popularity_baseline"][period] = popularity_baseline(conn, *date_ranges[period])
        artifact = json.loads(history_artifact.read_text(encoding="utf-8"))
        output["history_model_baseline"] = {
            "status": "not_comparable_on_known_periods",
            "model_version": artifact["model_version"],
            "trained_through": artifact["trained_through"],
            "reason": "The only current artifact was trained through 2026-07-11, later than both known periods.",
            "prospective_use": "Compare on shadow races strictly after trained_through.",
        }
        return output
    finally:
        conn.close()


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# v89・ベースライン既知期間比較",
        "",
        "判定用途: **診断のみ**。発走前odds snapshotがないため、昇格根拠には再利用しない。",
        "",
        "| period | venue | tickets | ROI | no-max | no-top3 | axis top3 | partner top3 | hit rate | target rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for period, value in report["v89"].items():
        for venue, metrics in {"combined": value["combined"], **value["by_course"]}.items():
            lines.append(
                f"| {period} | {venue} | {metrics['tickets']} | {metrics['roi']} | {metrics['roi_without_max']} | "
                f"{metrics['roi_without_top3']} | {metrics['axis_top3_rate']} | {metrics['partner_top3_rate']} | "
                f"{metrics['hit_rate']} | {metrics['ticket_target_rate']} |"
            )
    lines.extend(["", "## 単純人気baseline（1番人気の3着内率）", ""])
    for period, venues in report["simple_popularity_baseline"].items():
        lines.append(f"- {period}: `{venues}`")
    history = report["history_model_baseline"]
    lines.extend(
        [
            "",
            "## 既存履歴モデルbaseline",
            "",
            f"- status: `{history['status']}`",
            f"- artifact: `{history['model_version']}`, trained_through `{history['trained_through']}`",
            f"- reason: {history['reason']}",
            "",
            "## 解釈",
            "",
            "- v89は既知期間で高いROIを示しても、市場値が結果ページ由来でas-ofを証明できない。",
            "- 現行履歴artifactは既知期間より後まで学習済みのため、同期間baselineへ使うと未来情報混入になる。",
            "- よって新規候補探索は行わず、v89順位ルールを凍結したshadow比較へ進む。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--source-dir", type=Path, default=Path(".workstate/jra-srb/prediction-v1-validation"))
    parser.add_argument("--history-artifact", type=Path, default=Path("data/models/jra_history_recent_form_v2/model.json"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "artifacts")
    args = parser.parse_args()
    report = build(args.db, args.source_dir, args.history_artifact)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "known_baseline_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.output_dir / "known_baseline_comparison.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "v89": report["v89"], "history_model_baseline": report["history_model_baseline"]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

