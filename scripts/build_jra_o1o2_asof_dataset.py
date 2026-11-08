"""Build race-level, result-separated O1/O2 datasets from completed JV records."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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

JST = timezone(timedelta(hours=9))
PARSER_VERSION = "jv-o1o2-v2"
DATASET_VERSION = "jra_o1o2_asof_v1"
HORIZONS = {"T-30m": 30, "T-10m": 10}
PAYOUT_MARKETS = {"win": "win", "単勝": "win", "quinella": "quinella", "馬連": "quinella"}


def readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("BEGIN")
    return conn


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise OSError(f"SHA-256計算中に読めないファイル: {path}: {exc}") from exc
    return digest.hexdigest()


def source_file_hash(path: Path) -> dict:
    result = {"path": str(path.resolve()), "hashed_at": datetime.now(JST).isoformat(timespec="seconds")}
    try:
        result["sha256"] = file_sha256(path)
    except PermissionError:
        result["sha256"] = None
        result["hash_status"] = "windows_sharing_violation"
    except OSError as exc:
        if isinstance(exc.__cause__, PermissionError):
            result["sha256"] = None
            result["hash_status"] = "windows_sharing_violation"
        else:
            raise
    wal_path = Path(str(path) + "-wal")
    try:
        result["wal_sha256"] = file_sha256(wal_path)
    except OSError as exc:
        if isinstance(exc.__cause__, PermissionError):
            result["wal_sha256"] = None
            result["wal_hash_status"] = "windows_sharing_violation"
        else:
            raise
    return result


def logical_jv_source_sha256(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table, query in (
        ("jv_request_checkpoints", "SELECT jv_race_key,data_spec,status,completed_at FROM jv_request_checkpoints WHERE data_spec IN ('0B41','0B42') ORDER BY jv_race_key,data_spec"),
        ("jv_raw_records", "SELECT raw_record_id,jv_race_key,data_spec,sequence_no,sha256,bytes,retrieved_at,local_path FROM jv_raw_records WHERE data_spec IN ('0B41','0B42') ORDER BY raw_record_id"),
    ):
        digest.update((table + "\n").encode("ascii"))
        for row in conn.execute(query):
            digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def json_line(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def valid_race_id(race_id: str) -> bool:
    if len(race_id) != 12 or not race_id.isdigit() or race_id[8:10] not in history.COURSE_CODES:
        return False
    try:
        return date.fromisoformat(f"{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}").strftime("%Y%m%d") == race_id[:8]
    except ValueError:
        return False


def race_day(race_id: str) -> str:
    return f"{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}"


def start_datetime(day: str, value: str | None) -> datetime | None:
    match = re.search(r"(\d{1,2})\s*(?:時|:)(\d{2})", value or "")
    if not match:
        return None
    try:
        d = date.fromisoformat(day)
        return datetime(d.year, d.month, d.day, int(match.group(1)), int(match.group(2)), tzinfo=JST)
    except ValueError:
        return None


def parse_rank(value) -> int | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def horse_numbers(value: str) -> list[str]:
    return [str(int(number)) for number in re.findall(r"\d+", value or "")]


def load_analysis(conn: sqlite3.Connection):
    races = {}
    for row in conn.execute("SELECT race_id,race_date,course,race_no,race_name,start_time,surface,distance,source,fetched_at FROM races"):
        if valid_race_id(str(row["race_id"])):
            races[row["race_id"]] = dict(row)
    runners = defaultdict(list)
    for row in conn.execute("SELECT race_id,horse_no,frame_no,horse_name,sex_age,weight_carried,jockey,trainer,horse_weight,horse_weight_diff,status FROM runners"):
        if row["race_id"] in races:
            runners[row["race_id"]].append(dict(row))
    for rows in runners.values():
        rows.sort(key=lambda item: int(item["horse_no"]) if str(item["horse_no"]).isdigit() else 999)
    ranks = defaultdict(dict)
    for row in conn.execute("SELECT race_id,horse_no,rank FROM result_entries"):
        if row["race_id"] in races:
            value = parse_rank(row["rank"])
            if value is not None:
                ranks[row["race_id"]][str(row["horse_no"])] = value
    payouts = defaultdict(lambda: defaultdict(list))
    for row in conn.execute("SELECT race_id,bet_type,combination,payout FROM payouts"):
        market = PAYOUT_MARKETS.get(row["bet_type"])
        if market and row["race_id"] in races and row["payout"] is not None:
            payouts[row["race_id"]][market].append({"numbers": horse_numbers(row["combination"]),
                                                    "payout": int(row["payout"]), "source": "payouts"})
    fallback_payouts = defaultdict(lambda: defaultdict(list))
    for row in conn.execute("SELECT jra_race_id,bet_type,combination,payout FROM netkeiba_payouts"):
        market = PAYOUT_MARKETS.get(row["bet_type"])
        key = row["jra_race_id"]
        if market and key in races and row["payout"] is not None:
            fallback_payouts[key][market].append({"numbers": horse_numbers(row["combination"]),
                                                  "payout": int(row["payout"]), "source": "netkeiba_payouts"})
    for race_id, markets in fallback_payouts.items():
        for market, items in markets.items():
            if not payouts[race_id][market]:
                payouts[race_id][market].extend(items)
    cards = defaultdict(list)
    for row in conn.execute("SELECT * FROM race_card_snapshots WHERE runner_set_status='complete' AND source_kind='pre_race_card'"):
        if row["race_id"] in races:
            cards[row["race_id"]].append(dict(row))
    card_runners = defaultdict(list)
    for row in conn.execute("SELECT * FROM race_card_snapshot_runners"):
        card_runners[row["card_snapshot_id"]].append(dict(row))
    for entries in cards.values():
        entries.sort(key=lambda item: item["fetched_at"])
    return races, runners, ranks, payouts, cards, card_runners


class PastForm:
    def __init__(self):
        self.horse = defaultdict(history.HistoryStat)
        self.horse_course = defaultdict(history.HistoryStat)
        self.horse_surface = defaultdict(history.HistoryStat)
        self.horse_distance = defaultdict(history.HistoryStat)
        self.jockey = defaultdict(history.HistoryStat)
        self.trainer = defaultdict(history.HistoryStat)

    def features(self, race_id: str, race: dict, runner: dict, field_size: int) -> dict:
        day = date.fromisoformat(race_day(race_id))
        course = history.COURSE_CODES[race_id[8:10]]
        surface = history._surface(race.get("surface"))
        distance = history._number(race.get("distance")) or 0
        band = history._distance_band(distance, race.get("race_name"))
        horse_name = history._text(runner.get("horse_name"), "unknown")
        jockey = history._text(runner.get("jockey"), "unknown")
        trainer = history._text(runner.get("trainer"), "unknown")
        values = history._feature_vector(
            row=runner, race_date=day, race_name=history._text(race.get("race_name"), ""),
            course=course, surface=surface, distance=distance, field_size=field_size,
            horse=self.horse[horse_name], horse_course=self.horse_course[(horse_name, course)],
            horse_surface=self.horse_surface[(horse_name, surface)],
            horse_distance=self.horse_distance[(horse_name, band)],
            jockey=self.jockey[jockey], trainer=self.trainer[trainer],
        )
        return dict(zip(history.FEATURE_NAMES, values, strict=True))

    def update_day(self, race_ids: list[str], races: dict, runners: dict, ranks: dict) -> None:
        for race_id in race_ids:
            race = races.get(race_id)
            if race is None:
                continue
            ranked = [runner for runner in runners.get(race_id, []) if str(runner["horse_no"]) in ranks.get(race_id, {})]
            if len(ranked) < 2:
                continue
            if any(str(runner["horse_no"]) not in ranks.get(race_id, {}) and runner.get("status") == "active"
                   for runner in runners.get(race_id, [])):
                continue
            day = date.fromisoformat(race_day(race_id))
            course = history.COURSE_CODES[race_id[8:10]]
            surface = history._surface(race.get("surface"))
            distance = history._number(race.get("distance")) or 0
            band = history._distance_band(distance, race.get("race_name"))
            for runner in ranked:
                number = str(runner["horse_no"])
                rank = ranks[race_id][number]
                name = history._text(runner.get("horse_name"), "unknown")
                jockey = history._text(runner.get("jockey"), "unknown")
                trainer = history._text(runner.get("trainer"), "unknown")
                for stat in (
                    self.horse[name], self.horse_course[(name, course)],
                    self.horse_surface[(name, surface)], self.horse_distance[(name, band)],
                    self.jockey[jockey], self.trainer[trainer],
                ):
                    stat.update(rank, len(ranked), day)


def load_checkpoints(source: sqlite3.Connection, parsed: sqlite3.Connection):
    source_rows = {}
    universe = set()
    for row in source.execute("SELECT jv_race_key,data_spec,status,completed_at FROM jv_request_checkpoints WHERE data_spec IN ('0B41','0B42')"):
        race_id = row["jv_race_key"]
        if valid_race_id(race_id):
            universe.add(race_id)
            source_rows[(race_id, row["data_spec"])] = dict(row)
    parsed_rows = {}
    for row in parsed.execute("SELECT jv_race_key,data_spec,status,parser_version,source_record_count,parsed_records,rejected_records,source_manifest_sha256 FROM odds_import_checkpoints WHERE parser_version=?", (PARSER_VERSION,)):
        parsed_rows[(row["jv_race_key"], row["data_spec"])] = dict(row)
    return universe, source_rows, parsed_rows


def snapshot(source: sqlite3.Connection, parsed: sqlite3.Connection, race_id: str, spec: str,
             cutoff: datetime, source_cp: dict | None, parsed_cp: dict | None):
    if not source_cp or source_cp["status"] != "completed" or not source_cp["completed_at"]:
        return None, "source_checkpoint_missing"
    if (not parsed_cp or parsed_cp["status"] != "completed" or parsed_cp["rejected_records"] != 0
            or parsed_cp["parsed_records"] != parsed_cp["source_record_count"]):
        return None, "parser_checkpoint_incomplete"
    cursor = parsed.execute(
        "SELECT raw_record_id,announced_at,retrieved_at,source_sha256,source_bytes,source_local_path "
        "FROM jv_odds_observations WHERE jv_race_key=? AND source_data_spec=? AND parser_version=? "
        "AND data_division='1' AND announced_at_status='resolved' AND announced_at<=? "
        "ORDER BY announced_at DESC,raw_record_id DESC",
        (race_id, spec, PARSER_VERSION, cutoff.isoformat(timespec="minutes")),
    )
    first = cursor.fetchone()
    cursor.close()
    if first is None:
        return None, "no_intermediate_odds_before_cutoff"
    same_time = parsed.execute(
        "SELECT raw_record_id,source_sha256 FROM jv_odds_observations WHERE jv_race_key=? "
        "AND source_data_spec=? AND parser_version=? AND data_division='1' "
        "AND announced_at_status='resolved' AND announced_at=?",
        (race_id, spec, PARSER_VERSION, first["announced_at"]),
    ).fetchall()
    if len({row["source_sha256"].lower() for row in same_time}) > 1:
        return None, "conflicting_latest_announcement"
    original = source.execute(
        "SELECT sha256,bytes,local_path FROM jv_raw_records WHERE raw_record_id=?",
        (first["raw_record_id"],),
    ).fetchone()
    if (not original or original["sha256"].lower() != first["source_sha256"].lower()
            or original["bytes"] != first["source_bytes"] or original["local_path"] != first["source_local_path"]):
        return None, "raw_provenance_mismatch"
    announced = datetime.fromisoformat(first["announced_at"])
    if announced > cutoff:
        return None, "announcement_after_cutoff"
    market = "win" if spec == "0B41" else "quinella"
    items = []
    for entry in parsed.execute(
        "SELECT selection_key,odds_status_low,odds_low_x10,popularity FROM jv_odds_entries "
        "WHERE raw_record_id=? AND parser_version=? AND market=? ORDER BY selection_key",
        (first["raw_record_id"], PARSER_VERSION, market),
    ):
        key = entry["selection_key"]
        if not key.isdigit():
            continue
        valid = entry["odds_status_low"] == "numeric" and entry["odds_low_x10"] is not None and entry["odds_low_x10"] > 0
        odds = entry["odds_low_x10"] / 10 if valid else None
        if spec == "0B41":
            items.append({"horse_no": str(int(key)), "odds": odds, "popularity": entry["popularity"],
                          "status": entry["odds_status_low"]})
        elif len(key) == 4:
            items.append({"horse_no_1": str(int(key[:2])), "horse_no_2": str(int(key[2:])),
                          "odds": odds, "popularity": entry["popularity"], "status": entry["odds_status_low"]})
    if not items:
        return None, "no_odds_entries"
    if spec == "0B42" and not any(item["odds"] is not None for item in items):
        return None, "no_numeric_quinella_pairs"
    result = {
        "announced_at": first["announced_at"], "retrieved_at": first["retrieved_at"],
        "availability_evidence": ("retrieved_by_cutoff" if datetime.fromisoformat(first["retrieved_at"]) <= cutoff
                                  else "announced_before_cutoff_retrieved_later"),
        "age_minutes": round((cutoff - announced).total_seconds() / 60, 3),
        "raw_record_id": first["raw_record_id"], "raw_sha256": first["source_sha256"],
        "raw_bytes": first["source_bytes"], "raw_path": first["source_local_path"],
        "source_checkpoint_completed_at": source_cp["completed_at"],
        "parser_version": PARSER_VERSION,
        "horses" if spec == "0B41" else "pairs": items,
    }
    return result, None


def payout_rows(raw: list[dict], market: str) -> list[dict]:
    values = []
    seen = set()
    for item in raw:
        numbers = item["numbers"]
        if item["payout"] > 0 and ((market == "win" and len(numbers) == 1) or (market == "quinella" and len(numbers) == 2)):
            row = {"payout": item["payout"]}
            if market == "win":
                row["horse_no"] = numbers[0]
            else:
                row["horse_no_1"], row["horse_no_2"] = sorted(numbers, key=int)
            key = json_line(row)
            if key not in seen:
                values.append(row)
                seen.add(key)
    return values


def age_summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {"count": len(values), "min": ordered[0], "median": ordered[len(values) // 2],
            "p95": ordered[min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)], "max": ordered[-1],
            "over_10m": sum(value > 10 for value in values), "over_30m": sum(value > 30 for value in values)}


def build(args: argparse.Namespace) -> list[dict]:
    source = readonly(args.source_db)
    parsed = readonly(args.odds_db)
    analysis = readonly(args.analysis_db)
    try:
        races, runners, ranks, payouts, cards, card_runners = load_analysis(analysis)
        source_universe, source_cp, parsed_cp = load_checkpoints(source, parsed)
        odds_coverage = defaultdict(lambda: {
            "source_completed_pairs": Counter(), "parser_completed_pairs": Counter(),
            "parser_missing_or_incomplete_pairs": Counter(),
        })
        for (race_id, spec), source_checkpoint in source_cp.items():
            if source_checkpoint["status"] != "completed":
                continue
            year = race_id[:4]
            odds_coverage[year]["source_completed_pairs"][spec] += 1
            parsed_checkpoint = parsed_cp.get((race_id, spec))
            if (parsed_checkpoint and parsed_checkpoint["status"] == "completed"
                    and parsed_checkpoint["rejected_records"] == 0
                    and parsed_checkpoint["parsed_records"] == parsed_checkpoint["source_record_count"]):
                odds_coverage[year]["parser_completed_pairs"][spec] += 1
            else:
                odds_coverage[year]["parser_missing_or_incomplete_pairs"][spec] += 1
        universe = sorted((race_id for race_id in source_universe | set(races)
                           if args.through_date is None or race_day(race_id) <= args.through_date),
                          key=lambda value: (race_day(value), value))
        years = sorted({race_id[:4] for race_id in universe})
        if not years:
            raise RuntimeError("対象レースがありません")
        base = args.output_root / DATASET_VERSION
        base.mkdir(parents=True, exist_ok=True)
        for year in years:
            if (base / year).exists():
                raise FileExistsError(f"既存の年別成果物は上書きしません: {base / year}")
        source_files = {name: source_file_hash(path) for name, path in (
            ("jvlink.sqlite", args.source_db), ("odds-parsed.sqlite", args.odds_db),
            ("analysis.sqlite", args.analysis_db),
        )}
        source_files["jvlink.sqlite"]["logical_o1o2_sha256"] = logical_jv_source_sha256(source)
        states = PastForm()
        by_day = defaultdict(list)
        history_by_day = defaultdict(list)
        for race_id in universe:
            by_day[race_day(race_id)].append(race_id)
        for race_id, rank_map in ranks.items():
            if rank_map:
                history_by_day[race_day(race_id)].append(race_id)
        summary = []
        active_year = None
        context = None

        def finish_year() -> None:
            nonlocal context
            if context is None:
                return
            context["rows_handle"].close()
            context["excluded_handle"].close()
            year = context["year"]
            pending = context["pending"]
            rows_path = pending / "races.jsonl.gz"
            excluded_path = pending / "excluded.jsonl.gz"
            counts = context["counts"]
            manifest = {
                "dataset_version": DATASET_VERSION, "year": int(year), "schema_version": "race_asof_v1",
                "through_date": args.through_date,
                "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
                "horizons": HORIZONS, "parser_version": PARSER_VERSION,
                "adoption_rule": "T-30m and T-10m numeric O1 win snapshots, result ranks, and win payout required; O2 quinella optional",
                "all_races": counts["all_races"], "adopted_races": counts["adopted_races"],
                "excluded_races": counts["excluded_races"],
                "excluded_by_reason": dict(context["reasons"]),
                "monthly": {month: {"all": data["all"], "adopted": data["adopted"], "excluded": data["excluded"],
                                    "excluded_by_reason": dict(context["month_reasons"][month]),
                                    "odds_age_minutes": {name: age_summary(values) for name, values in
                                                         context["month_ages"][month].items()}}
                            for month, data in sorted(context["monthly"].items())},
                "quinella_missing_by_horizon": dict(context["quinella_missing"]),
                "quinella_missing_by_reason": dict(context["quinella_missing_reasons"]),
                "odds_age_minutes": {name: age_summary(values) for name, values in context["ages"].items()},
                "odds_age_scope": "available snapshots across adopted and excluded races",
                "odds_availability_evidence_counts": dict(context["availability"]),
                "history_policy": "Only result rows from dates strictly before target race_date; history begins at earliest available result date",
                "history_source_min_date": min(history_by_day) if history_by_day else None,
                "start_time_policy": "verified only with a complete race_card_snapshot fetched by T-30m; otherwise historical_schedule_unverified",
                "historical_card_policy": "When no pre-T-30m card exists, retrospective card identity is marked unverified; mutable horse weight and status are suppressed",
                "card_asof_status_counts": dict(context["card_status"]),
                "source_databases": source_files,
                "odds_source_parser_coverage": {
                    year_key: {key: dict(value) for key, value in odds_coverage.get(year_key, {}).items()}
                    for year_key in sorted(odds_coverage)
                },
                "database_hash_scope": "Physical SQLite main and WAL when readable; JV O1/O2 checkpoint/raw-record logical hash and selected input hash also recorded",
                "input_rows_sha256": context["input_digest"].hexdigest(),
                "generator_sha256": file_sha256(Path(__file__).resolve()),
                "files": {
                    "races.jsonl.gz": {"sha256": file_sha256(rows_path), "bytes": rows_path.stat().st_size},
                    "excluded.jsonl.gz": {"sha256": file_sha256(excluded_path), "bytes": excluded_path.stat().st_size},
                },
            }
            (pending / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8", newline="\n")
            final = base / year
            pending.rename(final)
            summary.append({"year": int(year), "all": counts["all_races"], "adopted": counts["adopted_races"],
                            "excluded": counts["excluded_races"], "path": str(final)})
            print(f"生成完了: {year} all={counts['all_races']} adopted={counts['adopted_races']} excluded={counts['excluded_races']}", flush=True)
            context = None

        for day in sorted(set(by_day) | set(history_by_day)):
            for race_id in by_day.get(day, []):
                year = race_id[:4]
                if active_year != year:
                    finish_year()
                    active_year = year
                    pending = base / f"{year}.pending-{uuid.uuid4().hex[:8]}"
                    pending.mkdir()
                    context = {
                        "year": year, "pending": pending,
                        "rows_handle": gzip.open(pending / "races.jsonl.gz", "wt", encoding="utf-8", newline="\n"),
                        "excluded_handle": gzip.open(pending / "excluded.jsonl.gz", "wt", encoding="utf-8", newline="\n"),
                        "counts": Counter(), "monthly": defaultdict(Counter), "reasons": Counter(),
                        "month_reasons": defaultdict(Counter), "quinella_missing": Counter(),
                        "quinella_missing_reasons": Counter(),
                        "ages": defaultdict(list), "month_ages": defaultdict(lambda: defaultdict(list)),
                        "input_digest": hashlib.sha256(),
                        "card_status": Counter(), "availability": Counter(),
                    }
                race = races.get(race_id)
                month = day[:7]
                context["counts"]["all_races"] += 1
                context["monthly"][month]["all"] += 1
                reasons = []
                if race is None:
                    reasons.append("missing_analysis_race")
                    context["excluded_handle"].write(json_line({"race_id": race_id, "race_date": day, "reasons": reasons}))
                    context["counts"]["excluded_races"] += 1
                    context["monthly"][month]["excluded"] += 1
                    context["reasons"].update(reasons)
                    context["month_reasons"][month].update(reasons)
                    continue
                start = start_datetime(day, race.get("start_time"))
                chosen_card = None
                for candidate in cards.get(race_id, []):
                    candidate_start = start_datetime(day, candidate.get("start_time"))
                    fetched = datetime.fromisoformat(candidate["fetched_at"])
                    if start and candidate_start == start and fetched <= start - timedelta(minutes=30):
                        chosen_card = candidate
                if chosen_card is not None:
                    race = chosen_card
                    start = start_datetime(day, race.get("start_time"))
                if race["race_date"] != day:
                    reasons.append("race_date_mismatch")
                if race["race_no"] != int(race_id[-2:]):
                    reasons.append("race_number_mismatch")
                if not race.get("race_name"):
                    reasons.append("missing_race_name")
                if history._surface(race.get("surface")) == "other":
                    reasons.append("missing_surface")
                if not (history._number(race.get("distance")) or 0):
                    reasons.append("missing_distance")
                if start is None:
                    reasons.append("missing_start_time")
                runner_rows = (card_runners[chosen_card["card_snapshot_id"]] if chosen_card is not None
                               else runners.get(race_id, []))
                if not runner_rows:
                    reasons.append("missing_runners")
                rank_map = ranks.get(race_id, {})
                runner_numbers = {str(runner["horse_no"]) for runner in runner_rows}
                if not rank_map:
                    reasons.append("missing_result_ranks")
                elif not set(rank_map).issubset(runner_numbers):
                    reasons.append("result_runner_mismatch")
                elif any(str(runner["horse_no"]) not in rank_map and runner.get("status") == "active"
                         for runner in runner_rows):
                    reasons.append("incomplete_result_ranks")
                win_payout = payout_rows(payouts[race_id]["win"], "win")
                if not win_payout:
                    reasons.append("missing_win_payout")
                elif rank_map and any(rank_map.get(item["horse_no"]) != 1 for item in win_payout):
                    reasons.append("win_payout_result_mismatch")
                odds_at = {}
                for horizon, minutes in HORIZONS.items():
                    if start is None:
                        odds_at[horizon] = {"win": None, "quinella": None}
                        continue
                    cutoff = start - timedelta(minutes=minutes)
                    win, win_reason = snapshot(source, parsed, race_id, "0B41", cutoff,
                                               source_cp.get((race_id, "0B41")), parsed_cp.get((race_id, "0B41")))
                    quinella, quinella_reason = snapshot(source, parsed, race_id, "0B42", cutoff,
                                                         source_cp.get((race_id, "0B42")), parsed_cp.get((race_id, "0B42")))
                    if not win:
                        reasons.append(f"missing_win_{horizon}:{win_reason}")
                    else:
                        numeric_horses = {item["horse_no"] for item in win["horses"] if item["odds"] is not None}
                        if not rank_map or not set(rank_map).issubset(numeric_horses):
                            reasons.append(f"incomplete_win_runner_odds_{horizon}")
                    if quinella is None:
                        context["quinella_missing"][horizon] += 1
                        context["quinella_missing_reasons"][f"{horizon}:{quinella_reason}"] += 1
                    odds_at[horizon] = {"win": win, "quinella": quinella}
                    if win:
                        context["ages"][f"{horizon}.win"].append(win["age_minutes"])
                        context["month_ages"][month][f"{horizon}.win"].append(win["age_minutes"])
                        context["availability"][f"{horizon}.win.{win['availability_evidence']}"] += 1
                    if quinella:
                        context["ages"][f"{horizon}.quinella"].append(quinella["age_minutes"])
                        context["month_ages"][month][f"{horizon}.quinella"].append(quinella["age_minutes"])
                        context["availability"][f"{horizon}.quinella.{quinella['availability_evidence']}"] += 1
                if reasons:
                    context["counts"]["excluded_races"] += 1
                    context["monthly"][month]["excluded"] += 1
                    context["reasons"].update(reasons)
                    context["month_reasons"][month].update(reasons)
                    context["excluded_handle"].write(json_line({"race_id": race_id, "race_date": day,
                        "reasons": reasons, "has_quinella": {h: bool(v["quinella"]) for h, v in odds_at.items()}}))
                    continue
                course = history.COURSE_CODES[race_id[8:10]]
                surface = history._surface(race.get("surface"))
                distance = history._number(race.get("distance"))
                card_fetched = datetime.fromisoformat(race["fetched_at"]) if race.get("fetched_at") else None
                first_cutoff = start - timedelta(minutes=30)
                start_status = "verified" if chosen_card is not None else "historical_schedule_unverified"
                runner_inputs = []
                for runner in runner_rows:
                    runner_inputs.append({
                        "horse_no": str(runner["horse_no"]), "horse_name": runner["horse_name"],
                        "frame_no": runner["frame_no"], "sex_age": runner["sex_age"],
                        "weight_carried": runner["weight_carried"],
                        "horse_weight": runner["horse_weight"] if chosen_card is not None else None,
                        "horse_weight_diff": runner["horse_weight_diff"] if chosen_card is not None else None,
                        "status": runner["status"] if chosen_card is not None else "historical_card_unverified",
                        "jockey": runner["jockey"], "trainer": runner["trainer"],
                        "history_features": states.features(race_id, race, runner, len(rank_map)),
                    })
                record = {
                    "race_id": race_id, "race_date": day,
                    "race": {"course": course, "race_no": race["race_no"], "race_name": race["race_name"],
                             "surface": surface, "distance": distance,
                             "start_at": start.isoformat(timespec="minutes"), "start_time_status": start_status},
                    "inputs": {"runners": runner_inputs, "history_as_of": f"{day}T00:00:00+09:00",
                               "card_source": race["source"], "card_fetched_at": race["fetched_at"],
                               "card_snapshot_id": chosen_card["card_snapshot_id"] if chosen_card is not None else None,
                               "card_asof_status": "verified" if chosen_card is not None else "historical_card_unverified",
                               "odds": odds_at},
                    "result": {"ranks_by_horse": rank_map,
                               "win_payout_per_100_yen": win_payout,
                               "quinella_payout_per_100_yen": payout_rows(payouts[race_id]["quinella"], "quinella")},
                    "source_refs": {"analysis_db": str(args.analysis_db.resolve()), "race_id": race_id,
                                    "result_table": "result_entries", "payout_tables": sorted({item["source"] for market in payouts[race_id].values() for item in market})},
                }
                context["rows_handle"].write(json_line(record))
                context["counts"]["adopted_races"] += 1
                context["card_status"]["verified" if chosen_card is not None else "historical_card_unverified"] += 1
                context["monthly"][month]["adopted"] += 1
                context["input_digest"].update(json_line({"race_id": race_id, "race": race,
                    "runners": runner_rows, "ranks": rank_map, "payouts": payouts[race_id],
                    "odds_refs": {h: {m: (v[m]["raw_record_id"], v[m]["raw_sha256"]) if v[m] else None
                                           for m in ("win", "quinella")} for h, v in odds_at.items()}}).encode("utf-8"))
            states.update_day(history_by_day.get(day, []), races, runners, ranks)
        finish_year()
        return summary
    finally:
        analysis.close()
        parsed.close()
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate annual as-of O1/O2 race datasets")
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument("--odds-db", required=True, type=Path)
    parser.add_argument("--analysis-db", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--through-date", type=lambda value: date.fromisoformat(value).isoformat(),
                        help="YYYY-MM-DD; inclusive")
    args = parser.parse_args()
    print(json.dumps(build(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
