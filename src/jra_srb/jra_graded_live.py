"""概要: 対応する三重賞の当日入力を検査し、固定研究v2の全頭予想を計算する。
作成日: 2026-11-14。
入力: 同名重賞の保存dataset、照合済み当日カード・国内履歴・5群設定。
出力: 全頭の3着内参考確率、基準値、特徴、計算根拠。
実行例: uv run python scripts/run_jra_graded_live.py predict --help
注意事項: 外部通信・DB更新・再学習なし。未校正の参考値で着順予測ではない。
"""

from datetime import date
import math
import unicodedata

from .jra_graded_patterns import build_examples, feature_values, surface
from .jra_race_conditions import public_runner, require, make_features
from .jra_conditions_refinement import group_deltas, candidate_prediction
from .jra_conditions_stability import bounded_probabilities


SERIES = {
    "musashino": {"name": "武蔵野ステークス", "venue": "05", "surface": "dirt", "distance": 1600},
    "daily2": {"name": "デイリー杯2歳ステークス", "venue": "08", "surface": "turf", "distance": 1600},
    "elizabeth": {"name": "エリザベス女王杯", "venue": "08", "surface": "turf", "distance": 2200},
}


def validate_live(card, history, series):
    """対象・馬ID・履歴の最新性を検査し、対象結果混入と不一致を拒否する。"""
    rule = SERIES[series]
    require(not any(k in card for k in ("rank", "outcome", "finish_rank", "result")), "live_target_result")
    require(unicodedata.normalize("NFKC", card["race_name"]) == rule["name"] and card["venue_code"] == rule["venue"]
            and card["distance"] == rule["distance"] and surface(card["track_code"]) == rule["surface"], "live_scope")
    require(card["race_key"] == card["race_date"].replace("-", "") + rule["venue"] + card["race_key"][-2:], "live_race_id")
    require(card["race_key"].isdigit() and len(card["race_key"]) == 12, "live_race_key")
    rows = card["runners"]
    require(4 <= len(rows) <= 18 and len({r["horse_no"] for r in rows}) == len(rows)
            and len({r["horse_id"] for r in rows}) == len(rows), "live_roster")
    require(len({(h["horse_id"], h["race_key"]) for h in history}) == len(history), "live_history_duplicates")
    require(all(h["race_date"] < card["race_date"] and h["race_key"] != card["race_key"] for h in history), "live_future_history")
    for r in rows:
        require(not any(k in r for k in ("rank", "outcome", "finish_rank")), "live_target_result")
        require(r["status"] == "active" and len(r["horse_id"]) == 10 and r["horse_id"].isdigit()
                and date.fromisoformat(card["race_date"]).year - int(r["horse_id"][:4]) == r["age"]
                and r["sex"] in ("1", "2", "3") and 1 <= r["frame_no"] <= 8
                and 40 <= r["weight_carried"] <= 70, "live_runner_attributes")
        require((r["age"] == 2) if series == "daily2" else (3 <= r["age"] <= 15), "live_age_scope")
        if series == "elizabeth":
            require(r["sex"] == "2", "live_elizabeth_female")
        prior = [h for h in history if h["horse_id"] == r["horse_id"] and h["status"] == "active"]
        require(bool(prior) and max(h["race_date"] for h in prior) == r["latest_race_date"],
                "live_latest_history_" + r["horse_no"])


def score_live(dataset, card, history, config, series):
    """過去比較と同じ5群・強度4・縮約20・±5pt制限で予想する。"""
    validate_live(card, history, series)
    source = {"races": [r for r in dataset["races"] if (r.get("series_id") == series
                        or series == "elizabeth" and r["race_name"] == SERIES[series]["name"])
                        and r["race_date"] < card["race_date"]], "history": dataset["history"]}
    original, resolved = build_examples(source), build_examples(source, True)
    candidate = {"pattern": "balanced", "family": "common", "weights": [1]*5,
                 "scale": 1, "shrinkage": 20, "half_life": None, "pooling": "hierarchical"}
    target = {**{k: v for k, v in card.items() if k != "runners"},
              "rows": [{**public_runner(r), "values": feature_values(card, r, history)} for r in card["runners"]]}
    base = candidate_prediction(group_deltas(original, target, config, candidate), target, candidate)
    quality = {**target, "rows": [{**public_runner(r), "values": feature_values(card, r, history, True)} for r in card["runners"]]}
    frozen = {**candidate, "pattern": "frozen_v2", "scale": 4}
    evidence = group_deltas(resolved, quality, config, frozen)
    raw = candidate_prediction(evidence, quality, frozen)
    baseline = {r["horse_no"]: r["probability_top3"] for r in base["runners"]}
    probabilities = bounded_probabilities([r["probability_top3"] for r in raw["runners"]],
                                          [baseline[r["horse_no"]] for r in raw["runners"]], .05)
    rows = [{**r, "probability_top3": p, "baseline_probability_top3": baseline[r["horse_no"]]}
            for r, p in zip(raw["runners"], probabilities, strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    require(abs(sum(r["probability_top3"] for r in rows)-3) < 1e-9 and all(
        math.isfinite(r["probability_top3"]) and 0 <= r["probability_top3"] <= 1
        and abs(r["probability_top3"]-r["baseline_probability_top3"]) <= .050000001 for r in rows), "live_probability")
    for i, r in enumerate(rows, 1):
        r.update(rank=i, mark="◎" if i == 1 else "○" if i == 2 else "▲" if i == 3 else "△" if i <= 6 else "―")
    return {"model": "frozen_v2", "runners": rows, "features": quality["rows"], "evidence": evidence,
            "history_state": [{"horse_no": r["horse_no"], **make_features(card, r, history)} for r in card["runners"]],
            "prior_races": len(original), "prior_latest_date": max(r["race_date"] for r in original),
            "probability_kind": "uncalibrated_top3_marginals", "finish_order_prediction_available": False}
