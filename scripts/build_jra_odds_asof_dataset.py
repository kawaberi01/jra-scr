from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jra_srb import jra_history_dataset as history

PARSER_VERSION = "jv-o1o2-v2"
JST = timezone(timedelta(hours=9))
ODDS_FEATURES = [
    "win_log_odds", "win_implied_probability", "win_probability_within_field",
    "place_log_odds_low", "place_log_odds_high", "odds_age_minutes_log1p",
    "win_odds_missing", "place_odds_missing", "odds_snapshot_missing",
]
FEATURE_NAMES = history.FEATURE_NAMES + ODDS_FEATURES


def ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_digest(refs: list[sqlite3.Row]) -> str:
    payload = [(r["raw_record_id"], r["sha256"].lower(), r["bytes"]) for r in refs]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("ascii")).hexdigest()


def get_race(source: sqlite3.Connection, race_id: str) -> list[dict]:
    return [dict(r) for r in source.execute("""
        SELECT r.race_id,r.race_date,r.race_name,r.surface,r.distance,r.start_time,r.source,r.fetched_at,
               ru.horse_no,ru.frame_no,ru.horse_name,ru.sex_age,ru.weight_carried,ru.jockey,ru.trainer,
               re.rank
        FROM races r JOIN runners ru ON ru.race_id=r.race_id
        JOIN result_entries re ON re.race_id=ru.race_id AND re.horse_no=ru.horse_no
        WHERE r.race_id=? ORDER BY CAST(ru.horse_no AS INTEGER)
    """, (race_id,))]


def parse_start(value: str, race_date: date) -> datetime | None:
    match = re.search(r"(\d{1,2})\s*(?:時|:)(\d{2})", value or "")
    if not match:
        return None
    return datetime.combine(race_date, datetime.min.time()).replace(
        hour=int(match.group(1)), minute=int(match.group(2)), tzinfo=JST
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Build immutable JV O1/O2 as-of training dataset")
    ap.add_argument("--source-db", type=Path, required=True)
    ap.add_argument("--odds-db", type=Path, required=True)
    ap.add_argument("--analysis-db", type=Path, required=True)
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--race-id", required=True, help="12-digit JV race key; prototype gate")
    ap.add_argument("--run-label", default="pilot")
    args = ap.parse_args()
    if len(args.race_id) != 12 or not args.race_id.isdigit():
        ap.error("--race-id は12桁の数字で指定してください")

    source, odds, analysis = ro(args.source_db), ro(args.odds_db), ro(args.analysis_db)
    run_id = datetime.now(JST).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    base = args.output_root / "jv_odds_asof" / "jv_odds_asof_v1"
    base.mkdir(parents=True, exist_ok=True)
    final = base / f"{run_id}-{args.run_label}"
    pending = final.with_name(final.name + ".pending")
    if final.exists() or pending.exists():
        raise FileExistsError(final)
    pending.mkdir()
    input_path = pending / "input_manifest.jsonl"
    quarantine_path = pending / "quarantine.jsonl"
    selected_refs: dict[str, dict] = {}
    pair_refs: dict[str, list[sqlite3.Row]] = {}
    quarantine: list[dict] = []
    try:
        card_rows = get_race(analysis, args.race_id)
        if not card_rows:
            raise RuntimeError("analysis.sqlite に結果付き出走行がありません")
        race = card_rows[0]
        race_date = date.fromisoformat(race["race_date"])
        start_time = parse_start(race["start_time"] or "", race_date)
        if start_time is None:
            raise RuntimeError("発走時刻を解析できないためカットオフを決められません")

        for spec in ("0B41", "0B42"):
            checkpoint = source.execute("SELECT status,completed_at FROM jv_request_checkpoints WHERE jv_race_key=? AND data_spec=?", (args.race_id, spec)).fetchone()
            parsed = odds.execute("SELECT status,source_record_count,source_manifest_sha256,parsed_records,rejected_records FROM odds_import_checkpoints WHERE jv_race_key=? AND data_spec=? AND parser_version=?", (args.race_id, spec, PARSER_VERSION)).fetchone()
            if not checkpoint or checkpoint["status"] != "completed" or not checkpoint["completed_at"]:
                quarantine.append({"race_id": args.race_id, "data_spec": spec, "reason": "source_checkpoint_not_completed"})
                continue
            refs = source.execute("SELECT raw_record_id,run_id,jv_race_key,data_spec,sequence_no,source_file_name,local_path,bytes,sha256,retrieved_at FROM jv_raw_records WHERE jv_race_key=? AND data_spec=? ORDER BY sequence_no,raw_record_id", (args.race_id, spec)).fetchall()
            if not parsed or parsed["status"] != "completed" or parsed["rejected_records"] != 0 or parsed["parsed_records"] != len(refs) or parsed["source_record_count"] != len(refs) or parsed["source_manifest_sha256"] != manifest_digest(refs):
                quarantine.append({"race_id": args.race_id, "data_spec": spec, "reason": "parsed_checkpoint_incomplete_or_mismatched", "source_count": len(refs)})
                continue
            pair_refs[spec] = refs
            for ref in refs:
                parsed_ref = odds.execute("SELECT status,source_sha256 FROM odds_import_records WHERE raw_record_id=? AND parser_version=?", (ref["raw_record_id"], PARSER_VERSION)).fetchone()
                if not parsed_ref or parsed_ref["status"] != "parsed" or parsed_ref["source_sha256"].lower() != ref["sha256"].lower():
                    raise RuntimeError(f"raw record parser provenance mismatch: {ref['raw_record_id']}")
                selected_refs[ref["raw_record_id"]] = dict(ref)

        if "0B41" not in pair_refs:
            raise RuntimeError("O1のcompletedペアが正規化DBで検証できません")

        with input_path.open("w", encoding="utf-8", newline="\n") as out:
            for spec, refs in sorted(pair_refs.items()):
                checkpoint = source.execute("SELECT completed_at FROM jv_request_checkpoints WHERE jv_race_key=? AND data_spec=? AND status='completed'", (args.race_id, spec)).fetchone()
                parser_checkpoint = odds.execute("SELECT source_manifest_sha256,parsed_records,rejected_records,processed_at FROM odds_import_checkpoints WHERE jv_race_key=? AND data_spec=? AND parser_version=?", (args.race_id, spec, PARSER_VERSION)).fetchone()
                for ref in refs:
                    out.write(json.dumps({"kind": "raw_record", "race_id": args.race_id, "data_spec": spec,
                        "source_checkpoint_completed_at": checkpoint[0], "raw_record_id": ref["raw_record_id"],
                        "sha256": ref["sha256"], "bytes": ref["bytes"], "local_path": ref["local_path"],
                        "retrieved_at": ref["retrieved_at"], "parser_version": PARSER_VERSION,
                        "parser_source_manifest_sha256": parser_checkpoint["source_manifest_sha256"],
                        "parser_processed_at": parser_checkpoint["processed_at"]}, ensure_ascii=False) + "\n")
                after = source.execute("SELECT status,completed_at FROM jv_request_checkpoints WHERE jv_race_key=? AND data_spec=?", (args.race_id, spec)).fetchone()
                if after["status"] != "completed" or after["completed_at"] != checkpoint[0]:
                    raise RuntimeError(f"source checkpoint changed during manifest creation: {spec}")

        cutoffs = {"T-30m": start_time - timedelta(minutes=30), "T-10m": start_time - timedelta(minutes=10)}
        snapshots: dict[tuple[str, str], dict] = {}
        for horizon, cutoff in cutoffs.items():
            for spec in ("0B41", "0B42"):
                if spec not in pair_refs:
                    continue
                obs = odds.execute("""SELECT o.raw_record_id,o.announced_at,o.data_division,o.source_sha256,o.source_bytes,o.source_local_path
                    FROM jv_odds_observations o WHERE o.jv_race_key=? AND o.source_data_spec=? AND o.parser_version=?
                    AND o.data_division='1' AND o.announced_at_status='resolved' AND o.announced_at<=?
                    ORDER BY o.announced_at DESC,o.raw_record_id""", (args.race_id, spec, PARSER_VERSION, cutoff.isoformat(timespec="minutes")))
                candidates = obs.fetchall()
                if not candidates:
                    continue
                latest_time = candidates[0]["announced_at"]
                same_time = [r for r in candidates if r["announced_at"] == latest_time]
                hashes = {r["source_sha256"].lower() for r in same_time}
                if len(hashes) > 1:
                    quarantine.append({"race_id": args.race_id, "horizon": horizon, "data_spec": spec, "reason": "conflicting_same_time_observations"})
                    continue
                winner = same_time[-1]
                snapshots[(horizon, spec)] = dict(winner)

        # Past-form states use only result dates strictly before this race date.
        prior = [dict(r) for r in analysis.execute("""SELECT r.race_id,r.race_date,r.race_name,r.surface,r.distance,
            ru.horse_no,ru.frame_no,ru.horse_name,ru.sex_age,ru.weight_carried,ru.jockey,ru.trainer,re.rank
            FROM races r JOIN runners ru ON ru.race_id=r.race_id
            JOIN result_entries re ON re.race_id=ru.race_id AND re.horse_no=ru.horse_no
            WHERE length(r.race_id)=12 AND substr(r.race_id,9,2) BETWEEN '01' AND '10'
            AND r.source LIKE 'https://www.jra.go.jp/%' AND r.race_date<?
            AND EXISTS(SELECT 1 FROM payouts p WHERE p.race_id=r.race_id)
            ORDER BY r.race_date,r.race_id,CAST(ru.horse_no AS INTEGER)""", (race["race_date"],))]
        states = history._build_history_states(prior)
        field_size = len(card_rows)
        course = history.COURSE_CODES[args.race_id[8:10]]
        surface = history._surface(race["surface"])
        distance = history._number(race["distance"]) or 0
        band = history._distance_band(distance, race["race_name"])
        output_rows = []
        for horizon, cutoff in cutoffs.items():
            o1 = snapshots.get((horizon, "0B41"))
            win_entries = {}
            place_entries = {}
            if o1:
                for row in odds.execute("SELECT market,selection_key,odds_low_x10,odds_high_x10,odds_status_low,odds_status_high FROM jv_odds_entries WHERE raw_record_id=? AND parser_version=? AND market IN ('win','place')", (o1["raw_record_id"], PARSER_VERSION)):
                    (win_entries if row["market"] == "win" else place_entries)[row["selection_key"].lstrip("0") or "0"] = dict(row)
            win_probs = {horse: 10.0 / r["odds_low_x10"] for horse, r in win_entries.items() if r["odds_status_low"] == "numeric" and r["odds_low_x10"]}
            total_prob = sum(win_probs.values())
            for row in card_rows:
                horse_no = str(row["horse_no"])
                horse_name = history._text(row["horse_name"], "unknown")
                jockey = history._text(row["jockey"], "unknown")
                trainer = history._text(row["trainer"], "unknown")
                base = history._feature_vector(row=row, race_date=race_date, race_name=history._text(race["race_name"], ""),
                    course=course, surface=surface, distance=distance, field_size=field_size,
                    horse=states["horse"][horse_name], horse_course=states["horse_course"][(horse_name, course)],
                    horse_surface=states["horse_surface"][(horse_name, surface)],
                    horse_distance=states["horse_distance"][(horse_name, band)],
                    jockey=states["jockey"][jockey], trainer=states["trainer"][trainer])
                wk = horse_no.zfill(2)
                w = win_entries.get(horse_no)
                p = place_entries.get(horse_no)
                valid_w = w and w["odds_status_low"] == "numeric" and w["odds_low_x10"]
                valid_pl = p and p["odds_status_low"] == "numeric" and p["odds_low_x10"] and p["odds_status_high"] == "numeric" and p["odds_high_x10"]
                winodds = (w["odds_low_x10"] / 10) if valid_w else None
                place_low = (p["odds_low_x10"] / 10) if valid_pl else None
                place_high = (p["odds_high_x10"] / 10) if valid_pl else None
                announced = datetime.fromisoformat(o1["announced_at"]) if o1 else None
                age = max(0.0, (cutoff - announced).total_seconds() / 60) if announced else 0.0
                odds_features = [math.log(winodds) if winodds else 0.0, 1.0 / winodds if winodds else 0.0,
                    win_probs.get(horse_no, 0.0) / total_prob if total_prob else 0.0,
                    math.log(place_low) if place_low else 0.0, math.log(place_high) if place_high else 0.0,
                    math.log1p(age), float(not bool(valid_w)), float(not bool(valid_pl)), float(not bool(o1))]
                features = base + odds_features
                if len(features) != len(FEATURE_NAMES) or not all(math.isfinite(float(x)) for x in features):
                    raise RuntimeError("特徴量の長さまたは有限値チェックに失敗")
                rank = int(row["rank"])
                if rank <= 0:
                    quarantine.append({"race_id": args.race_id, "horizon": horizon, "horse_no": horse_no, "reason": "invalid_result_label"})
                    continue
                def ref(spec: str):
                    snapshot = snapshots.get((horizon, spec))
                    return {"raw_record_id": snapshot["raw_record_id"], "announced_at": snapshot["announced_at"],
                            "sha256": snapshot["source_sha256"], "source_bytes": snapshot["source_bytes"],
                            "source_local_path": snapshot["source_local_path"]} if snapshot else None
                output_rows.append({"dataset_version": "jv_odds_asof_v1", "feature_version": "jra_history_v1_plus_odds_v1",
                    "race_id": args.race_id, "race_date": race["race_date"], "horizon": horizon,
                    "cutoff_at": cutoff.isoformat(timespec="minutes"), "horse_no": horse_no, "horse_name": horse_name,
                    "features": features, "feature_names": FEATURE_NAMES,
                    "label_win": int(rank == 1), "label_top3": int(rank <= 3), "actual_rank": rank,
                    "replay_status": "historical_reconstruction_start_time_unverified",
                    "source_refs": {"O1": ref("0B41"), "O2": ref("0B42"),
                        "label": {"database": str(args.analysis_db.resolve()), "table": "result_entries", "race_id": args.race_id, "horse_no": horse_no},
                        "analysis_card": {"source": race["source"], "fetched_at": race["fetched_at"], "start_time": race["start_time"]}}})

        rows_path = pending / "rows.jsonl.gz"
        with gzip.open(rows_path, "wt", encoding="utf-8", newline="\n") as out:
            for row in output_rows:
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        with quarantine_path.open("w", encoding="utf-8", newline="\n") as out:
            for item in quarantine:
                out.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        keys = [(r["race_id"], r["horizon"], r["horse_no"]) for r in output_rows]
        if len(keys) != len(set(keys)):
            raise RuntimeError("重複キー検出")
        counts = defaultdict(int)
        for row in output_rows:
            counts[row["horizon"]] += 1
            for value in row["features"]:
                if not math.isfinite(float(value)):
                    raise RuntimeError("非有限特徴量検出")
        manifest = {"dataset_version": "jv_odds_asof_v1", "run_id": run_id, "run_label": args.run_label,
            "generated_at": datetime.now(JST).isoformat(timespec="seconds"), "race_id": args.race_id,
            "generator_sha256": sha_file(Path(__file__).resolve()),
            "date_min": race["race_date"], "date_max": race["race_date"], "horizons": list(cutoffs),
            "feature_version": "jra_history_v1_plus_odds_v1", "feature_names": FEATURE_NAMES,
            "row_count": len(output_rows), "rows_by_horizon": dict(counts), "unique_keys": len(set(keys)),
            "raw_records_manifested": len(selected_refs), "quarantine_count": len(quarantine),
            "replay_status": "historical_reconstruction_start_time_unverified",
            "sources": {"source_db": str(args.source_db.resolve()), "odds_db": str(args.odds_db.resolve()), "analysis_db": str(args.analysis_db.resolve()), "parser_version": PARSER_VERSION},
            "files": {"rows.jsonl.gz": {"sha256": sha_file(rows_path), "bytes": rows_path.stat().st_size},
                "input_manifest.jsonl": {"sha256": sha_file(input_path), "bytes": input_path.stat().st_size},
                "quarantine.jsonl": {"sha256": sha_file(quarantine_path), "bytes": quarantine_path.stat().st_size}}}
        (pending / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        pending.rename(final)
        print(json.dumps({"output": str(final), "row_count": len(output_rows), "rows_by_horizon": dict(counts), "raw_records": len(selected_refs), "quarantine": len(quarantine)}, ensure_ascii=False))
        return 0
    except Exception:
        # Keep pending evidence for inspection; never publish a partial run as complete.
        raise
    finally:
        source.close()
        odds.close()
        analysis.close()


if __name__ == "__main__":
    raise SystemExit(main())
