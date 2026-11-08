"""Write a race-level V89 replay coverage dataset without inventing missing bets."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jra_srb import jra_v_theory as v89
from jra_srb.jra_history_dataset import COURSE_CODES

JST = timezone(timedelta(hours=9))
PARSER_VERSION = "jv-o1o2-v2"
DATASET_VERSION = "v89_recovery_v1"
SCHEMA_VERSION = "race_decision_audit_v1"
POLICY_VERSION = "v89-autumn-shadow-wide-asof-v1"


def open_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def start_at(race_day: date, text: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})\s*(?:時|:)(\d{2})", text or "")
    if not match:
        return None
    try:
        return datetime(race_day.year, race_day.month, race_day.day,
                        int(match.group(1)), int(match.group(2)), tzinfo=JST)
    except ValueError:
        return None


def historical_win(source: sqlite3.Connection, parsed: sqlite3.Connection,
                   race_id: str, cutoff: datetime | None) -> tuple[dict | None, str | None]:
    if cutoff is None:
        return None, "start_time_unresolved"
    source_cp = source.execute(
        "SELECT status,completed_at FROM jv_request_checkpoints WHERE jv_race_key=? AND data_spec='0B41'",
        (race_id,),
    ).fetchone()
    if not source_cp or source_cp["status"] != "completed":
        return None, "source_o1_not_completed"
    parser_cp = parsed.execute(
        "SELECT status,parsed_records,rejected_records,source_record_count FROM odds_import_checkpoints "
        "WHERE jv_race_key=? AND data_spec='0B41' AND parser_version=?",
        (race_id, PARSER_VERSION),
    ).fetchone()
    if (not parser_cp or parser_cp["status"] != "completed" or parser_cp["rejected_records"]
            or parser_cp["parsed_records"] != parser_cp["source_record_count"]):
        return None, "o1_parser_not_completed"
    candidates = parsed.execute(
        "SELECT raw_record_id,announced_at,retrieved_at,source_sha256,source_bytes,source_local_path "
        "FROM jv_odds_observations WHERE jv_race_key=? AND source_data_spec='0B41' "
        "AND parser_version=? AND data_division='1' AND announced_at_status='resolved' "
        "AND announced_at<=? ORDER BY announced_at DESC,raw_record_id",
        (race_id, PARSER_VERSION, cutoff.isoformat(timespec="minutes")),
    ).fetchall()
    if not candidates:
        return None, "no_o1_published_by_cutoff"
    latest = candidates[0]["announced_at"]
    same_time = [r for r in candidates if r["announced_at"] == latest]
    if len({r["source_sha256"].lower() for r in same_time}) > 1:
        return None, "conflicting_o1_at_same_time"
    chosen = same_time[-1]
    original = source.execute(
        "SELECT sha256,bytes,local_path FROM jv_raw_records WHERE raw_record_id=?",
        (chosen["raw_record_id"],),
    ).fetchone()
    if (not original or original["sha256"].lower() != chosen["source_sha256"].lower()
            or original["bytes"] != chosen["source_bytes"]
            or original["local_path"] != chosen["source_local_path"]):
        return None, "o1_source_reference_mismatch"
    odds = {}
    for row in parsed.execute(
        "SELECT selection_key,odds_status_low,odds_low_x10,popularity FROM jv_odds_entries "
        "WHERE raw_record_id=? AND parser_version=? AND market='win'",
        (chosen["raw_record_id"], PARSER_VERSION),
    ):
        horse_no = str(int(row["selection_key"]))
        valid = row["odds_status_low"] == "numeric" and row["odds_low_x10"] and row["odds_low_x10"] > 0
        odds[horse_no] = {"odds": row["odds_low_x10"] / 10 if valid else None,
                          "popularity": row["popularity"], "status": row["odds_status_low"]}
    return {
        "announced_at": chosen["announced_at"], "retrieved_at": chosen["retrieved_at"],
        "availability": "historical_publication_time_only",
        "raw_record_id": chosen["raw_record_id"], "sha256": chosen["source_sha256"],
        "bytes": chosen["source_bytes"], "local_path": chosen["source_local_path"],
        "source_checkpoint_completed_at": source_cp["completed_at"],
        "parser_version": PARSER_VERSION, "horses": odds,
    }, None


def history_rows(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT r.race_id,r.race_date,r.surface,r.distance,ru.horse_name,ru.jockey,ru.trainer,re.rank "
        "FROM races r JOIN runners ru ON ru.race_id=r.race_id "
        "JOIN result_entries re ON re.race_id=r.race_id AND re.horse_no=ru.horse_no "
        "WHERE r.race_date<=? AND r.source LIKE 'https://www.jra.go.jp/%' "
        "AND EXISTS(SELECT 1 FROM payouts p WHERE p.race_id=r.race_id) "
        "ORDER BY r.race_date,r.race_id,CAST(ru.horse_no AS INTEGER)",
        ("2025-12-31",),
    )


def race_rows(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT race_id,race_date,course,race_no,race_name,start_time,surface,distance,source,fetched_at "
        "FROM races WHERE race_date BETWEEN ? AND ? AND source LIKE 'https://www.jra.go.jp/%' "
        "ORDER BY race_date,race_id",
        ("2025-01-01", "2025-12-31"),
    )


def write_dataset(args: argparse.Namespace) -> dict:
    target = args.output_root / DATASET_VERSION / "2025"
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"既存成果物を上書きしません: {target}")
    target.mkdir(parents=True, exist_ok=True)
    pending = target / "races.jsonl.gz.pending"
    final_rows = target / "races.jsonl.gz"
    manifest_path = target / "manifest.json"
    analysis, source, parsed = (open_ro(args.analysis_db), open_ro(args.source_db), open_ro(args.odds_db))
    counts = Counter()
    input_dates: list[str] = []
    v89_hash = digest(args.v89_code)
    prior_by_horse: dict[str, list[dict]] = defaultdict(list)
    prior_by_jockey: dict[str, list[dict]] = defaultdict(list)
    prior_by_trainer: dict[str, list[dict]] = defaultdict(list)
    hist_cursor = history_rows(analysis)
    next_history = hist_cursor.fetchone()
    try:
        with gzip.open(pending, "wt", encoding="utf-8", newline="\n") as out:
            for race in race_rows(analysis):
                day = race["race_date"]
                race_id = race["race_id"]
                course = COURSE_CODES.get(race_id[8:10])
                if course is None:
                    raise RuntimeError(f"未対応の競馬場コード: {race_id}")
                if not input_dates or day != input_dates[-1]:
                    input_dates.append(day)
                # Only earlier dates enter the feature state. Today's results wait.
                while next_history is not None and next_history["race_date"] < day:
                    item = dict(next_history)
                    try:
                        valid = int(item["rank"]) > 0 and bool(item["horse_name"])
                    except (TypeError, ValueError):
                        valid = False
                    if valid:
                        prior_by_horse[item["horse_name"]].append(item)
                        if item["jockey"]:
                            prior_by_jockey[item["jockey"]].append(item)
                        if item["trainer"]:
                            prior_by_trainer[item["trainer"]].append(item)
                    next_history = hist_cursor.fetchone()
                race_day = date.fromisoformat(day)
                race_start = start_at(race_day, race["start_time"])
                cutoff = race_start - timedelta(minutes=args.offset_minutes) if race_start else None
                win, win_reason = historical_win(source, parsed, race_id, cutoff)
                runners = [dict(r) for r in analysis.execute(
                    "SELECT ru.horse_no,ru.frame_no,ru.horse_name,ru.sex_age,ru.weight_carried,"
                    "ru.jockey,ru.trainer,ru.horse_weight,ru.horse_weight_diff,ru.status,re.rank "
                    "FROM runners ru LEFT JOIN result_entries re ON re.race_id=ru.race_id AND re.horse_no=ru.horse_no "
                    "WHERE ru.race_id=? ORDER BY CAST(ru.horse_no AS INTEGER)", (race_id,))]
                history_state = {"horse": prior_by_horse, "jockey": prior_by_jockey,
                                 "trainer": prior_by_trainer}
                card = SimpleNamespace(surface=race["surface"], distance=race["distance"])
                for runner in runners:
                    runner["horse_no"] = str(runner["horse_no"])
                    runner["history_features"] = v89._features(
                        history_state, SimpleNamespace(**runner), course, card, len(runners)
                    )
                    runner["history_as_of"] = f"{day}T00:00:00+09:00"
                    runner["win_at_decision"] = win["horses"].get(runner["horse_no"]) if win else None
                    # The published result rank is a label, never a pre-race feature.
                    runner["actual_rank"] = runner.pop("rank")
                wide_history = [dict(r) for r in analysis.execute(
                    "SELECT s.snapshot_id,s.fetched_at,s.odds_timing,s.source FROM odds_snapshots s "
                    "WHERE s.race_id=? AND s.bet_type='wide' ORDER BY s.fetched_at",
                    (race_id,))]
                valid_wide = [r for r in wide_history if cutoff and datetime.fromisoformat(r["fetched_at"]) <= cutoff]
                payout = [dict(r) for r in analysis.execute(
                    "SELECT combination,payout,popularity FROM netkeiba_payouts "
                    "WHERE jra_race_id=? AND bet_type='wide' ORDER BY combination", (race_id,))]
                late_wide = analysis.execute(
                    "SELECT count(*),min(fetched_at),max(fetched_at) FROM netkeiba_odds_entries "
                    "WHERE jra_race_id=? AND bet_type='wide'", (race_id,),
                ).fetchone()
                reasons = []
                if not race_start:
                    reasons.append("start_time_unresolved")
                if not valid_wide:
                    reasons.append("wide_history_at_decision_unavailable")
                if win_reason:
                    reasons.append(win_reason)
                if not runners:
                    reasons.append("card_runners_unavailable")
                if not payout:
                    reasons.append("wide_payout_unavailable")
                # This 2025 export is an audit. No retroactive V89 ticket is invented.
                record = {
                    "dataset_version": DATASET_VERSION, "schema_version": SCHEMA_VERSION,
                    "race_id": race_id, "race_date": day,
                    "decision_at": cutoff.isoformat(timespec="minutes") if cutoff else None,
                    "horizon": f"T-{args.offset_minutes}m",
                    "race": {"course": course, "course_raw": race["course"], **{
                        key: race[key] for key in ("race_no", "race_name", "start_time", "surface", "distance")}},
                    "card": {"runners": runners, "source": race["source"], "fetched_at": race["fetched_at"],
                             "availability": "reconstructed_from_current_race_and_runner_rows"},
                    "win_market": win,
                    "wide_market": None,
                    "wide_history_snapshots": wide_history,
                    "late_wide_reference": {"entry_count": late_wide[0], "first_fetched_at": late_wide[1], "last_fetched_at": late_wide[2], "used_for_decision": False},
                    "v89": {"theory_version": "v89", "ticket_policy_version": POLICY_VERSION,
                            "code_path": str(args.v89_code.resolve()), "code_sha256": v89_hash,
                            "amount_per_ticket_yen": args.amount_per_ticket},
                    "decision": {"status": "unknown", "purchase_allowed": None, "tickets": None,
                                 "stake_yen": None, "reason": "insufficient_asof_wide_market"},
                    "result": {"ranks_by_horse": {r["horse_no"]: r["actual_rank"] for r in runners},
                               "wide_payout_per_100_yen": payout, "return_yen": None,
                               "recovery_rate": None},
                    "source_refs": {"analysis_db": str(args.analysis_db.resolve()),
                                    "source_db": str(args.source_db.resolve()),
                                    "odds_db": str(args.odds_db.resolve()),
                                    "result_tables": ["result_entries", "netkeiba_payouts"]},
                    "replay_status": "not_reconstructable", "replay_checks": {
                        "o1_published_by_decision": win is not None,
                        "o1_received_by_decision": bool(win and cutoff and datetime.fromisoformat(win["retrieved_at"]) <= cutoff),
                        "wide_received_by_decision": bool(valid_wide),
                        "card_pre_race_fetch_verified": bool(race["fetched_at"] and cutoff and datetime.fromisoformat(race["fetched_at"]) <= cutoff),
                    }, "missing_reasons": reasons,
                }
                if valid_wide:
                    # A complete replay adapter is required before V89 decisions are emitted.
                    record["replay_status"] = "wide_snapshot_found_replay_not_run"
                    record["decision"]["reason"] = "v89_replay_adapter_not_run"
                for reason in reasons:
                    counts["reason:" + reason] += 1
                counts["races"] += 1
                counts["runner_rows"] += len(runners)
                counts["races_with_o1_asof"] += win is not None
                counts["races_with_wide_asof"] += bool(valid_wide)
                counts["races_with_wide_payout"] += bool(payout)
                counts["races_without_weight_diff"] += all(r["horse_weight_diff"] is None for r in runners)
                out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        if counts["races"] == 0:
            raise RuntimeError("2025年のレースがありません")
        pending.replace(final_rows)
        manifest = {
            "dataset_version": DATASET_VERSION, "schema_version": SCHEMA_VERSION,
            "status": "coverage_audit_only", "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
            "period": {"from": "2025-01-01", "to": "2025-12-31"},
            "horizon": f"T-{args.offset_minutes}m", "amount_per_ticket_yen": args.amount_per_ticket,
            "v89": {"theory_version": "v89", "ticket_policy_version": POLICY_VERSION,
                    "code_path": str(args.v89_code.resolve()), "code_sha256": v89_hash},
            "counts": dict(counts), "decision_status_counts": {"unknown": counts["races"], "buy": 0, "no_buy": 0},
            "total_stake_yen": None, "total_return_yen": None, "recovery_rate": None,
            "generation_method": "Past result rows before each race date, completed O1 with announced_at<=cutoff, current race/card and final result rows; historical wide without verified decision-time publication is excluded.",
            "limitations": ["2025 wide snapshots at decision time are missing; no V89 purchase or ROI is calculated.",
                            "Current card rows were fetched after the race and do not prove the original card state.",
                            "O1 original retrieval after the event proves publication-time reconstruction only."],
            "sources": {"analysis_db": str(args.analysis_db.resolve()), "source_db": str(args.source_db.resolve()),
                        "odds_db": str(args.odds_db.resolve())},
            "files": {"races.jsonl.gz": {"sha256": digest(final_rows), "bytes": final_rows.stat().st_size}},
            "generator_sha256": digest(Path(__file__).resolve()),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return {"output": str(target), "races": counts["races"], "wide_asof": counts["races_with_wide_asof"],
                "o1_asof": counts["races_with_o1_asof"], "recovery_rate": None}
    finally:
        analysis.close()
        source.close()
        parsed.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-db", required=True, type=Path)
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument("--odds-db", required=True, type=Path)
    parser.add_argument("--v89-code", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--offset-minutes", type=int, default=10)
    parser.add_argument("--amount-per-ticket", type=int, default=100)
    args = parser.parse_args()
    if args.offset_minutes <= 0 or args.amount_per_ticket <= 0 or args.amount_per_ticket % 100:
        parser.error("offset は正、購入額は正の100円単位で指定してください")
    print(json.dumps(write_dataset(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
