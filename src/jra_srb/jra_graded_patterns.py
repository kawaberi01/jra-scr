"""概要: 同名三重賞の既知条件パターンを時系列・系列外で比較する。
作成日: 2026-11-14。
入力: 固定設定、保存dataset、SELECT専用研究reader。
出力: 追加二系列のdataset、全確率・指標・選択・汎用性診断。
実行例: uv run python scripts/run_jra_graded_patterns.py --help
注意事項: 2026結果・DB書込・既定モデル切替なし。事後属性による探索的研究。
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import random

from .jra_conditions_refinement import group_deltas, candidate_prediction
from .jra_conditions_search import score_prediction
from .jra_conditions_stability import bounded_probabilities
from .jra_race_conditions import make_features, require, aggregate, public_runner
from .jra_race_conditions_sql import ConditionsReader, normalize_row
from .jra_research_contracts import digest


def surface(code: str) -> str:
    """JRAトラックコードの平地芝/ダートを区別し、対象外はunknownとする。"""
    value = int(code)
    return "turf" if 10 <= value <= 22 else "dirt" if 23 <= value <= 29 else "unknown"


def export_additional(reader: ConditionsReader, config: dict) -> dict:
    """対象二系列と対象馬履歴を索引経路と分離SELECTで有界取得する。

    Notes:
        horse履歴の取得ではracesへ同時結合しない。metadataはhashで別取得する。
    """
    preflight = reader.preflight()
    series = [s for s in config["series"] if s["id"] != "elizabeth"]
    aliases = [a for s in series for a in s["aliases"]]
    targets = reader.rows("graded:targets", "SELECT TOP (101) race_key,CONVERT(varchar(10),race_date,23) race_date,"
        "venue_code,retrospective_metadata_json metadata,__unified_race_sha256 race_hash FROM history.races "
        "WHERE __migration_source_snapshot_id=31 AND race_date>=? AND race_date<? AND "
        "JSON_VALUE(retrospective_metadata_json,'$.race_name') IN (" + ",".join("?" for _ in aliases) + ") ORDER BY race_date,race_key",
        (f"{config['first_year']}-01-01", f"{config['last_year']+1}-01-01", *aliases), 100)
    require(len(targets) == 46, "graded_expected_46_editions")
    target_rows = []
    for start in range(0, len(targets), 25):
        target_rows.extend(normalize_row(row) for row in reader.target_entries(targets[start:start+25]))
    ids = sorted({r["horse_id"] for r in target_rows})
    require(len(ids) <= 1000 and all(len(i) == 10 and i.isdigit() for i in ids), "graded_horse_ids")
    values = ",".join("(CONVERT(nvarchar(10),?))" for _ in ids)
    entries = reader.rows("graded:entries_only", "SELECT TOP (20001) e.race_key,e.horse_id,e.horse_no,e.rank,e.abnormal_code,"
        "e.retrospective_se_json attrs,LEN(e.horse_id) id_length FROM history.entries e JOIN (VALUES " + values + ") h(id) "
        "ON CONVERT(nvarchar(10),e.horse_id)=h.id WHERE e.__migration_source_snapshot_id=31 "
        "AND CONVERT(nvarchar(12),e.race_key)<? OPTION (HASH JOIN)", (*ids, f"{config['last_year']+1}01010000"), 20000)
    require(all(r["id_length"] == 10 and str(r["horse_id"]) in ids for r in entries), "graded_horse_identity")
    # 2歳時の出走後に続く成馬の全キャリアは、その2歳戦の検証に使わない。
    latest_needed = {horse_id: max(r["race_date"].replace("-", "") for r in target_rows if r["horse_id"] == horse_id) for horse_id in ids}
    retrieved_entry_rows = len(entries)
    entries = [r for r in entries if r["race_key"][:8] < latest_needed[str(r["horse_id"])]]
    keys = sorted({r["race_key"] for r in entries})
    require(len(keys) <= 5000, "graded_metadata_cap")
    metadata = {}
    for start in range(0, len(keys), 64):
        chunk = keys[start:start+64]
        values = ",".join("(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))" for _ in chunk)
        params = [v for key in chunk for v in (hashlib.sha256(key.encode("utf-16le")).digest(), key)]
        rows = reader.rows("graded:metadata_by_hash", "SELECT r.race_key,CONVERT(varchar(10),r.race_date,23) race_date,"
            "r.venue_code,r.retrospective_metadata_json metadata FROM history.races r JOIN (VALUES " + values + ") k(h,key_value) "
            "ON r.__unified_race_sha256=k.h AND r.race_key=k.key_value WHERE r.__migration_source_snapshot_id=31", params, 64)
        for row in rows:
            require(row["race_key"] not in metadata, "graded_duplicate_metadata")
            metadata[row["race_key"]] = row
    require(set(keys) == set(metadata), "graded_missing_metadata")
    history = [normalize_row({**r, **metadata[r["race_key"]]}) for r in entries]
    conditions, audit = reader.race_conditions(set(keys) | {r["race_key"] for r in targets})
    for row in history + target_rows:
        condition = conditions.get(row["race_key"])
        row["ra_verified"] = condition is not None
        if condition:
            require(row["distance"] == int(condition["distance_raw"]) and row["track_code"] == condition["track_code"], "graded_RA_mismatch")
            row.update({k: condition[k] for k in ("grade", "weight_rule", "symbol")})
        for definition in series:
            if row["race_name"] in definition["aliases"]:
                row["race_name"] = definition["name"]
    races = []
    for target in targets:
        m = json.loads(target["metadata"])
        definition = next(s for s in series if m["race_name"] in s["aliases"])
        require(int(m["distance_raw"]) == definition["distance"] and surface(m["track_code"]) == definition["surface"], "graded_target_conditions")
        races.append({"series_id": definition["id"], "race_key": target["race_key"], "race_date": target["race_date"],
                      "race_name": definition["name"], "venue_code": target["venue_code"], "distance": int(m["distance_raw"]),
                      "track_code": m["track_code"], "runners": [r for r in target_rows if r["race_key"] == target["race_key"]]})
    output = {"schema_version": 1, "races": races, "history": history,
              "provenance": {"preflight": preflight, "raw_audit": audit, "query_metrics": reader.query_metrics,
                             "retrieved_entry_rows": retrieved_entry_rows, "needed_history_rows": len(entries),
                             "history_bound": "before_each_horses_last_target_edition"}}
    output["input_sha256"] = digest(output)
    return output


def feature_values(race: dict, runner: dict, history: list[dict], quality: bool = False) -> dict:
    """既存特徴を再利用し、同場距離実績の芝ダートと格別定義を適用する。"""
    from .jra_race_conditions import verified_conditions
    values = make_features(race, runner, history)["values"]
    prior = [h for h in history if h["horse_id"] == runner["horse_id"] and h["race_date"] < race["race_date"] and h["status"] == "active"]
    good = [h for h in prior if h.get("rank") and h["rank"] <= 3]
    if prior:
        values["course_distance_top3"] = "確認あり" if any(h["venue_code"] == race["venue_code"] and h["distance"] == race["distance"]
            and surface(h["track_code"]) == surface(race["track_code"]) for h in good) else "確認なし"
    if quality:
        labels = ["確認なし", "GIII2〜3着", "GIII勝利", "GII2〜3着", "GII勝利", "GI2〜3着", "GI勝利"]
        value = max([{"A": 5, "B": 3, "C": 1}[h["grade"]]+int(h["rank"] == 1) for h in good if h.get("grade") in ("A", "B", "C")], default=0)
        values["graded_top3"] = labels[value] if value or (prior and all(verified_conditions(h) for h in prior)) else None
    return values


def build_examples(dataset: dict, quality: bool = False) -> list[dict]:
    """2歳・牡牝・ダートを検査し、系列付きの事前特徴と結果を分離する。"""
    output = []
    for race in sorted(dataset["races"], key=lambda r: (r["race_date"], r["race_key"])):
        rows = [r for r in race["runners"] if r["status"] == "active"]
        require(4 <= len(rows) <= 18 and len({r["horse_id"] for r in rows}) == len(rows), "graded_roster")
        require(all(2 <= r["age"] <= 15 and r["sex"] in ("1", "2", "3") and 1 <= r["frame_no"] <= 8 and 40 <= r["weight_carried"] <= 70 for r in rows), "graded_runner_attributes")
        examples = [{**public_runner(r), "values": feature_values(race, r, dataset["history"], quality),
                     "outcome": {"top3": bool(r.get("rank") and r["rank"] <= 3)}} for r in rows]
        output.append({**{k: v for k, v in race.items() if k != "runners"}, "rows": examples,
                       "evaluation_eligible": sum(r["outcome"]["top3"] for r in examples) == 3})
    return output


def choose(annual: list[dict], patterns: list[dict]) -> str:
    """系列均等の一律比Brier改善率で選び、同率なら少数群を優先する。"""
    series = sorted({r["series_id"] for r in annual})
    scores = {}
    for pattern in patterns:
        skill = []
        for key in series:
            current = aggregate([r for r in annual if r["series_id"] == key and r["pattern"] == pattern["id"]])
            uniform = aggregate([r for r in annual if r["series_id"] == key and r["pattern"] == "uniform"])
            require(current["races"] > 0 and current["races"] == uniform["races"], "graded_selection_shape")
            skill.append(1-current["brier"]/uniform["brier"])
        scores[pattern["id"]] = sum(skill)/len(skill)
    best = max(scores.values())
    return min((p for p in patterns if scores[p["id"]] >= best-1e-12), key=lambda p: (len(p["groups"]), p["id"]))["id"]


def evaluate(datasets: dict[str, dict], base_config: dict, config: dict) -> dict:
    """各同名競走の過去年予測と、時系列/系列外の候補選択を比較する。"""
    annual, predictions, diagnostics = [], [], {}
    candidates = [{"pattern": p["id"], "family": "common", "weights": [int(i in p["groups"]) for i in range(5)],
                   "scale": 1, "shrinkage": 20, "half_life": None, "pooling": "hierarchical"} for p in config["patterns"]]
    candidate = {**candidates[-1], "pattern": "frozen_v2", "scale": 4}
    for series, dataset in datasets.items():
        require(dataset["input_sha256"] == digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "graded_dataset_sha")
        original = build_examples(dataset)
        resolved = build_examples(dataset, True)
        for race in original:
            race["series_id"] = series
        for race in resolved:
            race["series_id"] = series
        feature_rows = [row["values"] for race in original for row in race["rows"]]
        diagnostics[series] = {"editions": len(original), "runners": len(feature_rows), "history_rows": len(dataset["history"]),
            "features": {f: {"unknown": sum(v[f] is None for v in feature_rows), "distinct": len({v[f] for v in feature_rows if v[f] is not None})}
                         for f in feature_rows[0]}, "surface": sorted({surface(r["track_code"]) for r in original})}
        for target, quality in zip(original, resolved, strict=True):
            prior = [r for r in original if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
            if len(prior) < config["warmup_races"] or not target["evaluation_eligible"]:
                continue
            deltas = group_deltas(prior, target, base_config, candidates[-1])
            current = [candidate_prediction(deltas, target, c) for c in candidates]
            qprior = [r for r in resolved if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
            v2 = candidate_prediction(group_deltas(qprior, quality, base_config, candidate), quality, candidate)
            baseline = {r["horse_no"]: r["probability_top3"] for r in current[-1]["runners"]}
            capped = bounded_probabilities([r["probability_top3"] for r in v2["runners"]], [baseline[r["horse_no"]] for r in v2["runners"]], .05)
            v2["runners"] = sorted([{**r, "probability_top3": p} for r, p in zip(v2["runners"], capped, strict=True)], key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
            current.extend([v2, {"pattern": "uniform", "race_key": target["race_key"], "race_date": target["race_date"],
                "venue_code": target["venue_code"], "runners": [{"horse_no": r["horse_no"], "probability_top3": 3/len(target["rows"])} for r in target["rows"]]}])
            for prediction in current:
                prediction.update(series_id=series, prior_latest_date=max(r["race_date"] for r in prior), prior_races=len(prior))
                predictions.append(prediction)
                annual.append({k: prediction[k] for k in ("series_id", "pattern", "race_key", "race_date")} | score_prediction(prediction, target))
    summary = {s: {p: aggregate([r for r in annual if r["series_id"] == s and r["pattern"] == p])
                   for p in [c["pattern"] for c in candidates]+["frozen_v2", "uniform"]} for s in datasets}
    selection = []
    for target in annual:
        if target["pattern"] != "balanced":
            continue
        year = target["race_date"][:4]
        past = [r for r in annual if r["race_date"][:4] < year]
        for mode in ("own", "shared", "other_series"):
            pool = [r for r in past if mode == "shared" or (r["series_id"] == target["series_id"]) == (mode == "own")]
            needed = [target["series_id"]] if mode == "own" else [s for s in datasets if mode == "shared" or s != target["series_id"]]
            if any(len({r["race_date"][:4] for r in pool if r["series_id"] == s}) < config["selection_years"] for s in needed):
                continue
            chosen = choose(pool, config["patterns"])
            selected = next(r for r in annual if r["race_key"] == target["race_key"] and r["pattern"] == chosen)
            selection.append({**selected, "policy": mode, "selected_pattern": chosen,
                              "selection_latest_year": max(r["race_date"][:4] for r in pool), "selection_series": sorted({r["series_id"] for r in pool})})
    return {"summary": summary, "annual": annual, "predictions": predictions, "selection": selection,
            "diagnostics": diagnostics, "config_sha256": digest(config), "final_common_choice": choose(annual, config["patterns"])}


def selection_comparison(result: dict, config: dict) -> dict:
    """同じ外側評価年の系列均等改善率と年ブロック区間を保存する。"""
    output = {}
    for policy in ("own", "shared", "other_series"):
        rows = [r for r in result["selection"] if r["policy"] == policy]
        by_series = {}
        for series in result["summary"]:
            chosen = [r for r in rows if r["series_id"] == series]
            keys = {r["race_key"] for r in chosen}
            metrics = {p: aggregate([r for r in result["annual"] if r["race_key"] in keys and r["pattern"] == p]) for p in ("uniform", "balanced", "frozen_v2")}
            metrics["selected"] = aggregate(chosen)
            by_series[series] = metrics
        require(all(m["selected"]["races"] for m in by_series.values()), "graded_outer_empty")
        skill = sum(1-m["selected"]["brier"]/m["uniform"]["brier"] for m in by_series.values())/len(by_series)
        years = sorted({r["race_date"][:4] for r in rows})
        rng = random.Random(config["bootstrap_seed"])
        values = []
        for _ in range(config["bootstrap_repeats"]):
            counts = defaultdict(int)
            for year in rng.choices(years, k=len(years)):
                counts[year] += 1
            skills = []
            for series in by_series:
                picked = [r for r in rows if r["series_id"] == series]
                weights = [(r, counts[r["race_date"][:4]]) for r in picked]
                baseline = {r["race_key"]: r for r in result["annual"] if r["series_id"] == series and r["pattern"] == "uniform"}
                num = sum(r["brier"]*r["runners"]*n for r, n in weights)
                den = sum(baseline[r["race_key"]]["brier"]*r["runners"]*n for r, n in weights)
                skills.append(1-num/den)
            values.append(sum(skills)/len(skills))
        values.sort()
        output[policy] = {"series": by_series, "macro_skill_vs_uniform": skill,
                          "macro_skill_interval95": [values[int(.025*(len(values)-1))], values[int(.975*(len(values)-1))]],
                          "years": years, "bootstrap_unit": "calendar_year_block"}
    return output
