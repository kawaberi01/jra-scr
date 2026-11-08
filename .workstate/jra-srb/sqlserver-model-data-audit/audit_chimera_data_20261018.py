"""概要: キメラ初版に必要な時計・条件・相手履歴を全年度の固定SQL原文で監査する。
作成日: 2026-10-18
入力: 既存HistoryConfig、研究読取資格情報、2003〜2026年RA/SE、公式SDK。
出力: artifacts/diagnostics/chimera-data-<実行時刻>の集計JSON/CSVと進捗。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/audit_chimera_data_20261018.py
注意事項: SQL SELECTのみ。モデル学習・元データ複製・既定変更なし。対象日は2026-10-18未満。
"""

from collections import Counter, defaultdict, deque
import csv
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path

from jra_srb.jra_research_artifacts import ROOT, existing_run
from jra_srb.jra_research_contracts import ResearchError, digest
from jra_srb.jra_research_history import HistoryConfig
from jra_srb.jra_research_r1_live import LiveAnnualReader, read_json, require
from jra_srb.jra_research_resources import check_memory
from jra_srb import jra_research_tipster_twenty as native


BEFORE = "2026-10-18"
REFERENCE = "20261017T163427Z_79bd6188d33b46c19164600dd57840e8"


def save(path, value):
    """集計JSONを一時名から置き換え、途中停止しても直前の集計を保持する。"""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def clock_seconds(raw):
    """SEの4byte分秒欄を秒へ変換し、桁・秒部分・ゼロの異常を欠測とする。"""
    if len(raw) != 4 or not raw.isdigit() or int(raw) == 0 or int(raw[1:3]) >= 60:
        return None
    return int(raw[:1]) * 60 + int(raw[1:3]) + int(raw[3:4]) / 10


def inspect_race(race, source, seen, examples):
    """同日結果をまだ加えていない履歴から入力充足を集計する。

    Args:
        race: 既存の正常JRA平地・8頭以上の解析済み競走。
        source: SHA検証・版選択後のRA/SE。保存せずメモリで参照する。
        seen: 過去日だけの馬別件数と直近3走の観測有無。
        examples: 異常の競走キーを種類ごと最大5件保持する辞書。
    Returns:
        tuple: 集計Counterと、当日の全特徴集計後に更新する履歴。
    """
    ra = source["RA"][2]
    n, clocks, updates = len(race["runners"]), [], []
    turf = race["surface"] == 0
    going = native.number(ra[888:889] if turf else ra[889:890])
    lap_values = [native.number(ra[890 + i * 3:893 + i * 3]) / 10 for i in range(25)]
    lap_values = [v for v in lap_values if v > 0]
    c = Counter(races=1, runners=n, going_valid_races=int(going in (1, 2, 3, 4)),
                weather_valid_races=int(native.number(ra[887:888]) in range(1, 7)),
                pace_label_races=int(race["pace"] is not None))
    by_horse = {key: entry[2] for key, entry in source["SE"].items()}
    for r in race["runners"]:
        value = clock_seconds(by_horse[r["horse_no"]][338:342])
        valid = value is not None
        plausible = valid and 5 <= race["distance"] / value <= 25
        prior = seen.get(r["horse_id"])
        if prior is None:
            count, last = 0, []
        else:
            count, last = prior
            require(all(v[0] < race["ordinal"] for v in last), "chimera_audit_same_day_leak")
        recent_clock = sum(v[1] for v in last)
        recent_pace = sum(v[2] for v in last)
        c.update(clock_valid_runners=int(valid), clock_plausible_runners=int(plausible),
                 corner_valid_runners=int(r["corner"] is not None), closing_valid_runners=int(r["closing"] is not None),
                 prior_any_runners=int(count > 0), prior_clock1_runners=int(recent_clock >= 1),
                 prior_clock3_runners=int(recent_clock >= 3), prior_pace1_runners=int(recent_pace >= 1),
                 no_prior_runners=int(count == 0))
        if not valid and len(examples["invalid_clock"]) < 5:
            examples["invalid_clock"].append({"race_key": race["key"], "horse_no": r["horse_no"]})
        clocks.append((r["rank"], value))
        updates.append((r["horse_id"], (race["ordinal"], valid, race["pace"] is not None)))
    c["all_clock_valid_races"] = int(all(v is not None for _, v in clocks))
    c["all_clock_plausible_races"] = int(c["clock_plausible_runners"] == n)
    c["a_observed_races"] = int(c["all_clock_valid_races"] and going in (1, 2, 3, 4))
    c["all_prior_any_races"] = int(c["prior_any_runners"] == n)
    c["all_prior_clock1_races"] = int(c["prior_clock1_runners"] == n)
    c["all_prior_pace1_races"] = int(c["prior_pace1_runners"] == n)
    if c["all_clock_valid_races"]:
        ordered = sorted(clocks)
        c["clock_order_disagreement_races"] = int(any(a[1] > b[1] + .10001 for a, b in zip(ordered, ordered[1:])))
        if race["pace"] is not None:
            c["lap_clock_comparable_races"] = 1
            c["lap_clock_agree_races"] = int(abs(sum(lap_values) - ordered[0][1]) <= .15001)
            if not c["lap_clock_agree_races"] and len(examples["lap_clock_disagreement"]) < 5:
                examples["lap_clock_disagreement"].append({"race_key": race["key"], "absolute_difference_seconds": abs(sum(lap_values) - ordered[0][1])})
    return c, updates


def verify_totals(groups, annual):
    """年・月・場・距離の各別集計の件数一致と既知の分母を確認する。"""
    expected = sum(v["counts"]["races"] for v in annual.values())
    for axis in ("year", "month", "year_venue_surface", "year_distance"):
        require(sum(c["races"] for key, c in groups.items() if key[0] == axis) == expected,
                "chimera_audit_group_count_mismatch_" + axis)
    for c in groups.values():
        require(c["clock_valid_runners"] <= c["runners"] and c["a_observed_races"] <= c["races"]
                and c["prior_clock3_runners"] <= c["prior_clock1_runners"] <= c["prior_any_runners"] <= c["runners"],
                "chimera_audit_denominator_mismatch")


def execute():
    """全24年を既存索引経路で一巡し、集計・失敗証跡だけを新規保存する。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "artifacts/diagnostics" / ("chimera-data-" + stamp)
    path.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "before": BEFORE, "history_from": "2003-01-01", "annual": {}, "performance": "not_implemented_not_evaluated",
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "fixed_SQL_JV_normal_flat_unique_rank_at_least_8_runners",
              "sql_read_only": True, "new_model_fits": 0}
    save(path / "audit.json", report)
    print(json.dumps({"stage": "starting", "path": str(path)}), flush=True)
    groups, seen, examples = defaultdict(Counter), {}, defaultdict(list)
    reference = read_json(existing_run(REFERENCE) / "metrics.json")["coverage"]["years"]
    try:
        config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
        with LiveAnnualReader(config) as reader:
            report["preflight"] = reader.preflight()
            sdk = next(Path("D:/develop/jra-van-data/tools/jra-van-sdk").glob("**/JVData_Struct.cs"))
            definition = sdk.read_text(encoding="utf-8-sig")
            require("Time = MidB2S(ref bBuff, 339, 4);" in definition
                    and "TenkoBaba.SetDataB(MidB2B(ref bBuff, 888, 3));" in definition, "chimera_audit_sdk_layout_changed")
            report["sdk_offsets_one_based"] = {"SE_clock": [339, 4], "RA_weather_going": [888, 3], "RA_laps": [891, 75]}
            report["sdk_sha256"] = hashlib.sha256(sdk.read_bytes()).hexdigest()
            for year in range(2003, 2027):
                raw, source_audit = reader.year_before(year, BEFORE)
                parsed, excluded = defaultdict(list), Counter()
                first = last = None
                year_counts = Counter()
                for key, source in sorted(raw.items()):
                    race, reason = native.parse_race(key, source)
                    if reason:
                        excluded[reason] += 1
                        continue
                    parsed[race["day"]].append(race)
                for day, races in sorted(parsed.items()):
                    updates = []
                    for race in races:
                        c, new = inspect_race(race, raw[race["key"]], seen, examples)
                        updates.extend(new)
                        year_counts.update(c)
                        first, last = first or day, day
                        for axis, group in (("year", str(year)), ("month", day[:7]),
                                            ("year_venue_surface", f"{year}:{race['course']:02d}:{race['surface']}"),
                                            ("year_distance", f"{year}:{race['distance']}")):
                            groups[(axis, group)].update(c)
                    for horse_id, event in updates:
                        if horse_id not in seen:
                            seen[horse_id] = [0, deque(maxlen=3)]
                        seen[horse_id][0] += 1
                        seen[horse_id][1].append(event)
                report["annual"][str(year)] = {"source_races": len(raw), "counts": dict(year_counts),
                    "excluded": dict(excluded), "first_usable_day": first, "last_usable_day": last,
                    "source_audit": source_audit, "same_input_as_previous": source_audit["input_digest"] == reference[str(year)]["input_digest"]}
                save(path / "audit.json", report)
                print(json.dumps({"stage": "year", "year": year, "races": year_counts["races"],
                                  "runners": year_counts["runners"], "clock_valid": year_counts["clock_valid_runners"],
                                  "latest": last}), flush=True)
                del raw, parsed
                gc.collect()
                check_memory(2147483648)
        verify_totals(groups, report["annual"])
        totals = Counter()
        for value in report["annual"].values():
            totals.update(value["counts"])
        report.update(status="complete", finished_at_utc=datetime.now(timezone.utc).isoformat(), totals=dict(totals),
                      examples=dict(examples), group_count=len(groups), unique_horses=len(seen),
                      latest_usable_day=max(v["last_usable_day"] for v in report["annual"].values() if v["last_usable_day"]),
                      all_annual_input_digests_match_previous=all(v["same_input_as_previous"] for v in report["annual"].values()),
                      grouping_verified=True, caveats=["fixed_source_is_not_official_calendar_coverage",
                      "final_version_result_attributes_are_not_proven_pre_race_snapshots",
                      "missing_opening_history_before_2003", "new_model_performance_not_evaluated"])
        rows = [{"axis": key[0], "group": key[1], **dict(c)} for key, c in sorted(groups.items())]
        fields = ["axis", "group", *sorted({k for r in rows for k in r if k not in ("axis", "group")})]
        with (path / "coverage.csv").open("x", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields, restval=0)
            writer.writeheader()
            writer.writerows(rows)
        report["coverage_csv_sha256"] = hashlib.sha256((path / "coverage.csv").read_bytes()).hexdigest()
        save(path / "audit.json", report)
        print(json.dumps({"stage": "complete", "path": str(path), "totals": dict(totals),
                          "latest": report["latest_usable_day"]}), flush=True)
        return path
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__,
                      reason=error.reason if isinstance(error, ResearchError) else "audit_failed")
        save(path / "audit.json", report)
        raise


if __name__ == "__main__":
    execute()
