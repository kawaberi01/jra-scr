"""Read-only inventory for the tipster-method research; no model fitting."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DATA = ROOT / "data/training/jra_o1o2_asof_v1"
CASES = (
    ("Y1", "2025-07-27", "niigata", 7),
    ("Y2", "2026-05-31", "tokyo", 11),
    ("Y3", "2026-02-22", "tokyo", 5),
    ("M1", "2025-03-30", "nakayama", 11),
    ("M2", "2025-05-03", "tokyo", 11),
    ("K1", "2025-01-05", "chukyo", 11),
    ("K2", "2025-02-09", "tokyo", 11),
    ("K3", "2025-03-01", "nakayama", 11),
    ("K4", "2025-03-16", "chukyo", 11),
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    report = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "availability audit only; no prediction or ROI evaluation",
        "years": {},
        "case_matches": {},
    }
    ids = []
    total = Counter()
    for year in (2024, 2025, 2026):
        folder = DATA / str(year)
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hashes = {name: sha(folder / name) for name in
                  ("manifest.json", "races.jsonl.gz", "excluded.jsonl.gz")}
        count = Counter()
        race_keys, runner_keys, history_keys, odds_keys, result_keys = set(), set(), set(), set(), set()
        with gzip.open(folder / "races.jsonl.gz", "rt", encoding="utf-8") as stream:
            for line in stream:
                race = json.loads(line)
                ids.append(race["race_id"])
                count["races"] += 1
                race_keys.update(race["race"])
                result_keys.update(race["result"])
                odds_keys.update(race["inputs"]["odds"]["T-30m"])
                snapshot = race["inputs"]["odds"]["T-30m"].get("quinella")
                if snapshot and any(p.get("status") == "numeric" for p in snapshot.get("pairs", [])):
                    count["races_with_numeric_T30_quinella"] += 1
                for runner in race["inputs"]["runners"]:
                    count["runners"] += 1
                    runner_keys.update(runner)
                    features = runner.get("history_features", {})
                    history_keys.update(features)
                    for name in ("frame_no", "horse_weight", "horse_weight_diff"):
                        count[f"runner_nonnull_{name}"] += runner.get(name) is not None
                    count["runners_with_history"] += features.get("horse_has_history", 0) > 0
                    count["newcomer_runner_flags"] += features.get("is_newcomer", 0) > 0
                key = (race["race_date"], race["race"].get("course"), race["race"].get("race_no"))
                for case_id, date, course, race_no in CASES:
                    if key == (date, course, race_no):
                        report["case_matches"][case_id] = {"race_id": race["race_id"], "in_fixed_dataset": True}
        reasons = Counter()
        excluded_count = 0
        with gzip.open(folder / "excluded.jsonl.gz", "rt", encoding="utf-8") as stream:
            for line in stream:
                excluded = json.loads(line)
                excluded_count += 1
                reasons.update(excluded["reasons"])
        if count["races"] != manifest["adopted_races"] or excluded_count != manifest["excluded_races"]:
            raise ValueError(f"row count mismatch: {year}")
        if dict(reasons) != manifest["excluded_by_reason"]:
            raise ValueError(f"exclusion reasons mismatch: {year}")
        for name in ("races.jsonl.gz", "excluded.jsonl.gz"):
            if hashes[name] != manifest["files"][name]["sha256"]:
                raise ValueError(f"hash mismatch: {year}/{name}")
        report["years"][str(year)] = {
            "counts": dict(count), "hashes": hashes,
            "monthly_adopted": {m: v["adopted"] for m, v in manifest["monthly"].items()},
            "excluded_rows": excluded_count, "exclusion_reason_counts": dict(reasons),
            "race_keys": sorted(race_keys), "runner_keys": sorted(runner_keys),
            "history_keys": sorted(history_keys), "T30_odds_keys": sorted(odds_keys),
            "result_keys": sorted(result_keys),
        }
        total.update(count)
        if any(sha(folder / name) != value for name, value in hashes.items()):
            raise ValueError(f"source changed during audit: {year}")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate race ids")
    for case_id, date, course, race_no in CASES:
        report["case_matches"].setdefault(case_id, {"date": date, "course": course,
                                                    "race_no": race_no, "in_fixed_dataset": False})
    db = ROOT / "data/db/analysis.sqlite"
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        # Inventory existing retrospective material, without loading the JV-Link DB.
        queries = {
            "past_result_features_by_year": """
                SELECT substr(n.race_date,1,4) AS year, COUNT(*) AS result_rows,
                       COUNT(DISTINCT n.jra_race_id) AS races,
                       SUM(e.corner_order IS NOT NULL AND e.corner_order != '') AS corner_rows,
                       SUM(e.final_3f IS NOT NULL) AS final3f_rows
                FROM netkeiba_race_results n JOIN netkeiba_result_entries e
                  ON e.netkeiba_race_id=n.netkeiba_race_id
                WHERE n.race_date BETWEEN '2024-01-01' AND '2026-09-26'
                GROUP BY substr(n.race_date,1,4)""",
            "lap_races_by_year": """
                SELECT substr(race_date,1,4) AS year, COUNT(*) AS races,
                       SUM(race_laps_json IS NOT NULL AND race_laps_json NOT IN ('', '[]', 'null')) AS lap_races
                FROM netkeiba_race_results
                WHERE race_date BETWEEN '2024-01-01' AND '2026-09-26'
                GROUP BY substr(race_date,1,4)""",
            "wide_odds_by_year": """
                SELECT substr(r.race_date,1,4) AS year, COUNT(*) AS odds_rows,
                       COUNT(DISTINCT r.race_id) AS races, MIN(o.fetched_at) AS first_fetch,
                       MAX(o.fetched_at) AS last_fetch
                FROM netkeiba_odds_entries o JOIN races r ON r.race_id=o.jra_race_id
                WHERE o.bet_type='wide' AND r.race_date BETWEEN '2024-01-01' AND '2026-09-26'
                GROUP BY substr(r.race_date,1,4)""",
            "wide_payout_by_year": """
                SELECT substr(r.race_date,1,4) AS year, COUNT(*) AS payout_rows,
                       COUNT(DISTINCT r.race_id) AS races
                FROM netkeiba_payouts p JOIN races r ON r.race_id=p.jra_race_id
                WHERE p.bet_type='wide' AND r.race_date BETWEEN '2024-01-01' AND '2026-09-26'
                GROUP BY substr(r.race_date,1,4)""",
        }
        report["existing_analysis_db"] = {
            "path": str(db), "access_mode": "ro and query_only",
            "scope": "existing rows only; DB may be updated by other processes; not an as-of certification",
            **{key: [dict(row) for row in conn.execute(query)] for key, query in queries.items()},
        }
    finally:
        conn.close()
    report["totals"] = dict(total)
    report["source_checks"] = "manifest hashes, row counts, exclusion reasons, duplicate ids, before/after input hashes passed"
    path = OUT / "data_audit.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"totals": report["totals"], "existing_analysis_db": report["existing_analysis_db"],
                      "case_matches": report["case_matches"], "source_checks": report["source_checks"]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
