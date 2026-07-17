from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3


POLICY_VERSION = "history_win_ev_revalidation_v1"
REQUIRED_RATE = 0.95
MIN_EXTERNAL_RACES = 500


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def audit(db_path: Path, model_path: Path, from_date: str, to_date: str) -> dict:
    path = db_path.resolve()
    artifact = model_path.resolve()
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            with jra as (
                select r.race_id, r.race_date, coalesce(r.race_name, '') as race_name
                from races r
                where r.race_date between ? and ?
                  and length(r.race_id) = 12
                  and substr(r.race_id, 9, 2) between '01' and '10'
                  and r.source like 'https://www.jra.go.jp/%'
            ), flagged as (
                select jra.*,
                    exists(select 1 from result_entries re where re.race_id = jra.race_id and re.rank = 1) as has_result,
                    exists(select 1 from payouts p where p.race_id = jra.race_id and p.bet_type in ('win', '単勝') and p.payout is not null) as has_win_payout,
                    exists(select 1 from netkeiba_race_mappings m join netkeiba_race_results nr on nr.netkeiba_race_id = m.netkeiba_race_id where m.jra_race_id = jra.race_id) as has_netkeiba_result,
                    (select count(*) from result_entries re where re.race_id = jra.race_id) =
                    (select count(*) from result_entries re join netkeiba_race_mappings m on m.jra_race_id = re.race_id join netkeiba_result_entries ne on ne.netkeiba_race_id = m.netkeiba_race_id and ne.horse_no = re.horse_no where re.race_id = jra.race_id and ne.win_odds > 0) as has_final_win_odds,
                    (select count(*) from runners ru where ru.race_id = jra.race_id) as runner_count,
                    (select count(*) from result_entries re where re.race_id = jra.race_id and re.rank > 0) as ranked_runner_count,
                    (select count(*) from netkeiba_race_mappings m join netkeiba_result_entries ne on ne.netkeiba_race_id = m.netkeiba_race_id where m.jra_race_id = jra.race_id) as netkeiba_runner_count
                from jra
            )
            select * from flagged order by race_date, race_id
            """,
            (from_date, to_date),
        ).fetchall()

    excluded = {
        "newcomer": 0,
        "obstacle": 0,
        "missing_result": 0,
        "missing_win_payout": 0,
        "missing_final_win_odds": 0,
        "cancelled_or_excluded": 0,
    }
    eligible: list[sqlite3.Row] = []
    total_runner_rows = 0
    for row in rows:
        race_name = row["race_name"]
        if "新馬" in race_name or "メイクデビュー" in race_name:
            excluded["newcomer"] += 1
            continue
        if "障害" in race_name:
            excluded["obstacle"] += 1
            continue
        if not row["has_result"]:
            excluded["missing_result"] += 1
            continue
        if not row["has_win_payout"]:
            excluded["missing_win_payout"] += 1
            continue
        if not row["has_netkeiba_result"]:
            excluded["missing_final_win_odds"] += 1
            continue
        if row["runner_count"] != row["netkeiba_runner_count"]:
            excluded["cancelled_or_excluded"] += 1
            continue
        if not row["has_final_win_odds"]:
            excluded["missing_final_win_odds"] += 1
            continue
        eligible.append(row)
        total_runner_rows += row["ranked_runner_count"]

    normal_rows = [
        row for row in rows
        if "新馬" not in row["race_name"]
        and "メイクデビュー" not in row["race_name"]
        and "障害" not in row["race_name"]
    ]
    normal_count = len(normal_rows)
    quality_rows = [row for row in normal_rows if row["runner_count"] == row["netkeiba_runner_count"]]
    quality_count = len(quality_rows)
    result_count = sum(bool(row["has_result"]) for row in quality_rows)
    odds_count = sum(bool(row["has_final_win_odds"]) for row in quality_rows)
    payout_count = sum(bool(row["has_win_payout"]) for row in quality_rows)
    dates = [row["race_date"] for row in eligible]
    quality_ok = all(
        _rate(value, quality_count) >= REQUIRED_RATE
        for value in (result_count, odds_count, payout_count)
    )
    enough_external = len(eligible) >= MIN_EXTERNAL_RACES
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "policy_version": POLICY_VERSION,
        "input": {
            "dataset_path": str(path),
            "dataset_hash": _sha256(path),
            "model_artifact_path": str(artifact),
            "model_artifact_hash": _sha256(artifact) if artifact.is_file() else None,
        },
        "scope": {
            "race_type": "JRA normal flat races",
            "from_date": from_date,
            "to_date": to_date,
            "historical_final_odds_source": "netkeiba_result_entries.win_odds",
        },
        "counts": {
            "all_jra_races": len(rows),
            "normal_races_before_cancel_exclusion": normal_count,
            "quality_eligible_races": quality_count,
            "eligible_races": len(eligible),
            "eligible_runner_rows": total_runner_rows,
            "date_min": min(dates) if dates else None,
            "date_max": max(dates) if dates else None,
        },
        "coverage": {
            "result": {"count": result_count, "rate": _rate(result_count, quality_count)},
            "win_payout": {"count": payout_count, "rate": _rate(payout_count, quality_count)},
            "final_win_odds": {"count": odds_count, "rate": _rate(odds_count, quality_count)},
        },
        "excluded_races": excluded,
        "decision": {
            "status": "data_insufficient" if not (quality_ok and enough_external) else "ready_for_split",
            "required_coverage_rate": REQUIRED_RATE,
            "minimum_external_races": MIN_EXTERNAL_RACES,
            "quality_ok": quality_ok,
            "enough_external_races": enough_external,
            "next_step": "stop_revalidation" if not (quality_ok and enough_external) else "create_fixed_time_split",
        },
    }


def _markdown(report: dict) -> str:
    counts = report["counts"]
    coverage = report["coverage"]
    decision = report["decision"]
    return "\n".join((
        "# JRA通常戦 単勝EV データ監査",
        "",
        f"- 作成日時: {report['created_at']}",
        f"- dataset hash: `{report['input']['dataset_hash']}`",
        f"- model artifact hash: `{report['input']['model_artifact_hash']}`",
        f"- policy version: `{report['policy_version']}`",
        "",
        "## 結果",
        "",
        f"- 判定: `{decision['status']}`",
        f"- 対象通常戦（取消・除外前）: {counts['normal_races_before_cancel_exclusion']} レース",
        f"- 品質判定対象: {counts['quality_eligible_races']} レース",
        f"- 再検証可能: {counts['eligible_races']} レース / {counts['eligible_runner_rows']} runner",
        f"- 結果取得率: {coverage['result']['rate']:.2%}",
        f"- 単勝払戻取得率: {coverage['win_payout']['rate']:.2%}",
        f"- 最終単勝オッズ取得率: {coverage['final_win_odds']['rate']:.2%}",
        "",
        "## 停止判定",
        "",
        f"- 必須取得率基準: {decision['required_coverage_rate']:.0%}",
        f"- 外部評価の最小件数: {decision['minimum_external_races']} レース",
        f"- 次の扱い: `{decision['next_step']}`",
        "",
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for JRA history win-EV revalidation.")
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--model", type=Path, default=Path("data/models/jra_history_v1/model.json"))
    parser.add_argument("--from-date", default="2025-01-01")
    parser.add_argument("--to-date", default="2026-05-31")
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-win-ev-revalidation/artifacts"))
    args = parser.parse_args()
    report = audit(args.db, args.model, args.from_date, args.to_date)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "data-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    (args.output_dir / "data-audit.md").write_text(_markdown(report), encoding="utf-8", newline="\r\n")
    print(f"AUDIT_STATUS={report['decision']['status']}")
    return 0 if report["decision"]["status"] == "ready_for_split" else 2


if __name__ == "__main__":
    raise SystemExit(main())
