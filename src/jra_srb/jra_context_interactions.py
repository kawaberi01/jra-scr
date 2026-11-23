"""概要: 前走格と着順の結合・再対戦の相対斤量変化を福島記念で追加比較する。
作成日: 2026-11-21
入力: 監査済み履歴、直接対決の保存出力、固定設定。
出力: 2群の特徴と根拠、8方式144予測、追加除去比較・カバー率。
実行例: uv run python scripts/run_jra_context_interactions.py --help
注意事項: オフラインの探索的再検証。既知期間の最良方式選択・本採用・購入は行わない。
"""

from __future__ import annotations

from collections import defaultdict

from .jra_conditions_refinement import group_deltas
from .jra_head_to_head import compare
from .jra_race_conditions import probabilities, require, verified_conditions
from .jra_specific_patterns import metrics, weight_valid


def class_rank(race: dict, runner: dict, history: list[dict]) -> dict:
    """対象日前の直近確認走の格と着順を結合し、不明は欠測で保持する。"""
    prior = sorted([h for h in history if h["horse_id"] == runner["horse_id"] and h["race_date"] < race["race_date"] and h["status"] == "active"],
                   key=lambda h: (h["race_date"], h["race_key"]))
    require(len({h["race_date"] for h in prior}) == len(prior), "interaction_same_day_conflict")
    previous = prior[-1] if prior else None
    value = None
    if (previous and verified_conditions(previous) and previous.get("grade") is not None
            and type(previous.get("rank")) is int and previous["rank"] > 0):
        grade = previous["grade"] if previous.get("grade") in ("A", "B", "C") else "非ABC"
        rank = previous["rank"]
        bucket = "1着" if rank == 1 else "2〜3着" if rank <= 3 else "4〜5着" if rank <= 5 else "6着以下"
        value = grade+"|"+bucket
    return {"values": {"class_rank": value}, "previous_evidence": {k: previous.get(k) for k in
            ("race_key", "race_date", "race_name", "grade", "rank", "distance", "weight_carried")} if previous else None}


def weight_band(value: float | None, threshold: float) -> str | None:
    """相対負担変化の平均を固定kg境界で分類し、欠測を区別する。"""
    if value is None:
        return None
    return "相対軽化" if value <= -threshold else "相対重化" if value >= threshold else "概ね同じ"


def rematch_weight(runner: dict, roster: list[dict], meetings: list[dict], config: dict) -> dict:
    """過去の先着/後着相手別に、今回と過去の斤量差の変化を平均する。

    Args:
        runner: 今回の馬IDと斤量。
        roster: 今回の出走馬全頭の馬IDと斤量。
        meetings: 040で抽出済みの近距離の相手別直近対戦。
        config: 固定した1kg分類境界。
    Returns:
        後着/先着相手の2特徴、平均kg、採用/欠測の相手別根拠。
    """
    current = {r["horse_id"]: r for r in roster}
    require(len(current) == len(roster) and len({m["opponent_id"] for m in meetings}) == len(meetings), "interaction_duplicate_opponent")
    collected = {"lost_relative_weight": [], "won_relative_weight": []}
    ignored = []
    for meeting in meetings:
        opponent = current.get(meeting["opponent_id"])
        own_now = runner.get("weight_carried")
        other_now = opponent.get("weight_carried") if opponent else None
        own_before, other_before = meeting.get("own_weight"), meeting.get("opponent_weight")
        if meeting["comparison"] == 0:
            ignored.append({**meeting, "reason": "past_tie"})
            continue
        if not all(weight_valid(w) for w in (own_now, other_now, own_before, other_before)):
            ignored.append({**meeting, "reason": "missing_weight"})
            continue
        before, now = own_before-other_before, own_now-other_now
        feature = "lost_relative_weight" if meeting["comparison"] < 0 else "won_relative_weight"
        collected[feature].append({**meeting, "own_current_weight": own_now, "opponent_current_weight": other_now,
                                   "relative_before": before, "relative_now": now, "relative_change": now-before})
    means = {f: sum(m["relative_change"] for m in rows)/len(rows) if rows else None for f, rows in collected.items()}
    return {"values": {f: weight_band(v, config["weight_band_kg"]) for f, v in means.items()},
            "relative_change_means": means, "weight_meetings": collected, "ignored_meetings": ignored}


def variants() -> list[dict]:
    """一般評価にH/C/Wを追加する8固定方式を返し、最良方式は選ばない。"""
    return [{"mask": mask, "pattern": "general"+"".join("+"+name for bit, name in ((1,"h2h"),(2,"class"),(4,"weight")) if mask & bit)} for mask in range(8)]


def prediction(evidence: dict, target: dict, variant: dict, scale: float) -> dict:
    """既存一般スコアへ指定した群差分だけを加えて正規化する。"""
    delta = {group: {r["horse_id"]: r["deltas"][0] for r in rows} for group, rows in evidence.items() if group != "general"}
    scores = []
    for r in evidence["general"]:
        score = sum(r["deltas"])/len(r["deltas"])
        for bit, group in ((1,"h2h"),(2,"class"),(4,"weight")):
            if variant["mask"] & bit:
                score += scale*delta[group][r["horse_id"]]
        scores.append(score)
    probabilities_top3 = probabilities(scores)
    rows = [{k: r[k] for k in ("horse_id", "horse_no", "horse_name")} | {"probability_top3": p}
            for r, p in zip(evidence["general"], probabilities_top3, strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return {"pattern": variant["pattern"], "race_key": target["race_key"], "race_date": target["race_date"], "venue_code": target["venue_code"], "runners": rows}


def evaluate(data: dict, reference: dict, config: dict, general_config: dict) -> dict:
    """保存した直接対決基準を再利用し、2新群の追加除去を144予測で比較する。"""
    require(config["weight_band_kg"] == 1 and config["addition_scale"] == .5
            and config["lookback_days"] == 730 and config["distance_tolerance_m"] == 200, "interaction_fixed_protocol")
    historical = defaultdict(list)
    for h in data["history"]:
        historical[h["horse_id"]].append(h)
    base = reference["examples"]
    require(len(base) == 23 and len(reference["predictions"]) == 72, "interaction_reference_shape")
    source_evidence = {r["race_key"]: r for r in reference["evidence"]}
    class_examples, weight_examples, coverage = [], [], []
    for target in base:
        cr, wr = [], []
        for r in target["rows"]:
            cr.append({**r, **class_rank(target, r, historical[r["horse_id"]])})
            wr.append({**r, **rematch_weight(r, target["rows"], r["meetings"]["h2h_near_distance"], config)})
        class_examples.append({**target, "rows": cr})
        weight_examples.append({**target, "rows": wr})
        coverage.append({"race_key": target["race_key"], "race_date": target["race_date"], "runners": len(cr),
                         "class_known": sum(r["values"]["class_rank"] is not None for r in cr),
                         "lost_weight_known": sum(r["values"]["lost_relative_weight"] is not None for r in wr),
                         "won_weight_known": sum(r["values"]["won_relative_weight"] is not None for r in wr)})
    results, annual, evidence = [], [], []
    parameters = {"half_life": None, "pooling": "hierarchical", "shrinkage": 20}
    for i, target in enumerate(base):
        if i < 5:
            continue
        class_delta = group_deltas(class_examples[:i], class_examples[i], {**general_config, "groups": config["class_group"]}, parameters)
        weight_delta = group_deltas(weight_examples[:i], weight_examples[i], {**general_config, "groups": config["weight_group"]}, parameters)
        original = source_evidence[target["race_key"]]
        ev = {"general": original["general"], "h2h": original["head_to_head"], "class": class_delta, "weight": weight_delta}
        evidence.append({"race_key": target["race_key"], **ev})
        for variant in variants():
            p = prediction(ev, target, variant, config["addition_scale"])
            results.append(p)
            annual.append({"pattern": p["pattern"], "race_key": p["race_key"], "race_date": p["race_date"], **metrics(p, target)})
    require(len(results) == 144, "interaction_prediction_count")
    old = {(p["race_key"],p["pattern"]): p for p in reference["predictions"]}
    for p in results:
        if p["pattern"] in ("general", "general+h2h"):
            require(p["runners"] == old[(p["race_key"],p["pattern"])]["runners"], "interaction_baseline_changed")
    lookup = {v["mask"]: v["pattern"] for v in variants()}
    pairs = list(dict.fromkeys(tuple(p) for p in config["primary_comparisons"] +
                               [[lookup[m|bit],lookup[m]] for bit in (2,4) for m in range(8) if not m & bit]))
    comparisons = {a+"_vs_"+b: compare(annual+reference["uniform_reference"],a,b,config) for a,b in pairs}
    return {"protocol": config["protocol"], "evaluation_status": config["evaluation_status"],
            "predictions": results, "annual": annual, "class_examples": class_examples, "weight_examples": weight_examples,
            "evidence": evidence, "coverage": coverage, "comparisons": comparisons,
            "primary_comparison_keys": [a+"_vs_"+b for a,b in config["primary_comparisons"]]}
