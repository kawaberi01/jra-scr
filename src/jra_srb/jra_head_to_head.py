"""概要: 福島記念の出走馬同士の過去先着関係を作り、既存評価への追加効果を比較する。
作成日: 2026-11-21
入力: 監査済み正規化履歴、固定した直接対決設定、既存パーツ設定。
出力: 対戦特徴・根拠、4方式の予測と年別精度、探索的比較。
実行例: uv run python scripts/run_jra_head_to_head.py --help
注意事項: オフライン。参照済み期間の追加検証であり、独立確認・本採用・利益の実証ではない。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from itertools import combinations

from .jra_conditions_refinement import group_deltas
from .jra_graded_patterns import surface
from .jra_race_conditions import probabilities, require
from .jra_specific_patterns import make_examples, predict, metrics, mean_metrics, confirmation


def balance(items: list[dict]) -> str | None:
    """相手ごとの直近先着関係を3区分にし、対戦なしは欠測にする。"""
    if not items:
        return None
    score = sum(item["comparison"] for item in items)
    return "先着優勢" if score > 0 else "後着多い" if score < 0 else "均衡"


def features(race: dict, runners: list[dict], history: list[dict], config: dict) -> dict:
    """対象日前の同時出走だけを照合し、相手ごとの直近対戦と条件を返す。

    Args:
        race: 対象日、競走キー、芝距離を持つ競走。
        runners: 今回の有効出走馬。恒久馬IDと馬番を使う。
        history: 当該結果も含みうる保存走歴。関数内で対象日以後を除く。
        config: 固定の遡及日数と距離許容幅。
    Returns:
        馬ID別の2特徴、件数、条件付き対戦根拠。結果や未来走は含まない。
    """
    end = date.fromisoformat(race["race_date"])
    start = (end-timedelta(days=config["lookback_days"])).isoformat()
    names = {r["horse_id"]: r.get("horse_name", r["horse_id"]) for r in runners}
    require(len(names) == len(runners), "h2h_duplicate_roster")
    grouped, seen = defaultdict(list), set()
    for row in history:
        if (row["horse_id"] not in names or not start <= row["race_date"] < race["race_date"]
                or row["status"] != "active" or not row.get("rank") or row["rank"] < 1
                or surface(row["track_code"]) != "turf"):
            continue
        identity = (row["horse_id"], row["race_key"])
        require(identity not in seen, "h2h_duplicate_history")
        seen.add(identity)
        grouped[row["race_key"]].append(row)
    all_items = defaultdict(list)
    for key, rows in grouped.items():
        for a, b in combinations(rows, 2):
            require(all(a[k] == b[k] for k in ("race_date", "distance", "venue_code", "track_code")), "h2h_race_condition_conflict")
            for own, opponent in ((a, b), (b, a)):
                delta = (1 if own["rank"] < opponent["rank"] else -1 if own["rank"] > opponent["rank"] else 0)
                all_items[own["horse_id"]].append({
                    "opponent_id": opponent["horse_id"], "opponent_name": names[opponent["horse_id"]],
                    "race_key": key, "race_date": own["race_date"], "distance": own["distance"], "venue_code": own["venue_code"],
                    "own_rank": own["rank"], "opponent_rank": opponent["rank"], "comparison": delta,
                    "own_weight": own.get("weight_carried"), "opponent_weight": opponent.get("weight_carried"),
                    "weight_difference": own["weight_carried"]-opponent["weight_carried"] if own.get("weight_carried") is not None and opponent.get("weight_carried") is not None else None,
                    "days_before": (end-date.fromisoformat(own["race_date"])).days,
                    "near_distance": abs(own["distance"]-race["distance"]) <= config["distance_tolerance_m"]})
    output = {}
    for row in runners:
        selected = {}
        for feature, near in (("h2h_all_turf", False), ("h2h_near_distance", True)):
            by_opponent = {}
            for item in sorted(all_items[row["horse_id"]], key=lambda x: (x["race_date"], x["race_key"]), reverse=True):
                if (not near or item["near_distance"]) and item["opponent_id"] not in by_opponent:
                    by_opponent[item["opponent_id"]] = item
            selected[feature] = list(by_opponent.values())
        output[row["horse_id"]] = {"values": {f: balance(items) for f, items in selected.items()}, "meetings": selected}
    return output


def add_scores(base: list[dict], added: list[dict], target: dict, pattern: str, scale: float, group_index: int | None) -> dict:
    """未対戦の差分を0のまま既存スコアへ加え、合計3に正規化する。"""
    extra = {r["horse_id"]: r["deltas"][0] for r in added}
    scores = [(sum(r["deltas"])/len(r["deltas"]) if group_index is None else r["deltas"][group_index])
              + scale*extra[r["horse_id"]] for r in base]
    p = probabilities(scores)
    rows = [{k: r[k] for k in ("horse_id", "horse_no", "horse_name")} | {"probability_top3": v} for r, v in zip(base, p, strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return {"pattern": pattern, "race_key": target["race_key"], "race_date": target["race_date"], "venue_code": target["venue_code"], "runners": rows}


def compare(annual: list[dict], added: str, baseline: str, config: dict) -> dict:
    """既存基準で追加前後を比較するが、参照済み期間なので本採用にしない。"""
    renamed = [{**r, "pattern": "general" if r["pattern"] == baseline else r["pattern"]}
               for r in annual if r["pattern"] in (added, baseline, "uniform")]
    result = confirmation(renamed, added, config)
    result["reference_conditions_met"] = result.pop("adopted")
    result["adopted"] = False
    result["baseline"] = baseline
    result["status"] = "exploratory_seen_years_independent_confirmation_required"
    for field in ("summaries", "annual"):
        result[field][baseline] = result[field].pop("general")
        if field == "annual":
            result[field][baseline] = [{**r, "pattern": baseline} for r in result[field][baseline]]
    result["development"] = {p: mean_metrics([r for r in annual if r["pattern"] == p and config["development"][0] <= int(r["race_date"][:4]) <= config["development"][1]]) for p in (added, baseline)}
    return result


def evaluate(data: dict, config: dict, original_config: dict, general_config: dict) -> dict:
    """福島記念の既存2基準と対戦追加2方式を固定し、72予測を保存する。"""
    specific, general, _ = make_examples(data, "fukushima", original_config)
    by_horse = defaultdict(list)
    for row in data["history"]:
        by_horse[row["horse_id"]].append(row)
    enhanced, coverage = [], []
    for target in specific:
        ids = {r["horse_id"] for r in target["rows"]}
        relevant = [h for hid in ids for h in by_horse[hid]]
        direct = features(target, target["rows"], relevant, config)
        rows = [{**r, **direct[r["horse_id"]]} for r in target["rows"]]
        enhanced.append({**target, "rows": rows})
        coverage.append({"race_key": target["race_key"], "race_date": target["race_date"], "runners": len(rows),
                         "any_comparison": sum(r["values"]["h2h_all_turf"] is not None for r in rows),
                         "near_comparison": sum(r["values"]["h2h_near_distance"] is not None for r in rows)})
    scfg = {**general_config, "groups": original_config["series"]["fukushima"]["groups"]}
    hcfg = {**general_config, "groups": config["groups"]}
    predictions, annual, reference_uniform, evidence = [], [], [], []
    for i, target in enumerate(specific):
        if i < 5:
            continue
        gp, ge = predict(general[i], general[:i], general_config, {"pattern": "general", "family": "baseline", "weights": [1]*5, "scale": 1})
        np, ne = predict(target, specific[:i], scfg, {"pattern": "near", "family": "baseline", "weights": [0, 0, 1, 0], "scale": 1})
        he = group_deltas(enhanced[:i], enhanced[i], hcfg, {"half_life": None, "pooling": "hierarchical", "shrinkage": 20})
        evidence.append({"race_key": target["race_key"], "general": ge, "near": ne, "head_to_head": he})
        local = [gp, np, add_scores(ge, he, target, "general+h2h", config["head_to_head_scale"], None),
                 add_scores(ne, he, target, "near+h2h", config["head_to_head_scale"], 2)]
        for p in local:
            require(abs(sum(r["probability_top3"] for r in p["runners"])-3) < 1e-8, "h2h_probability_sum")
            predictions.append(p)
            annual.append({"pattern": p["pattern"], "race_key": target["race_key"], "race_date": target["race_date"], **metrics(p, target)})
        uniform = {**gp, "runners": [{**r, "probability_top3": 3/len(gp["runners"])} for r in gp["runners"]]}
        reference_uniform.append({"pattern": "uniform", "race_key": target["race_key"], "race_date": target["race_date"], **metrics(uniform, target)})
    require(len(predictions) == 72, "h2h_prediction_count")
    comparisons = {a+"_vs_"+b: compare(annual+reference_uniform, a, b, config) for a, b in config["comparisons"]}
    return {"protocol": config["protocol"], "evaluation_status": config["evaluation_status"],
            "predictions": predictions, "annual": annual, "uniform_reference": reference_uniform,
            "examples": enhanced, "evidence": evidence, "coverage": coverage, "comparisons": comparisons}
