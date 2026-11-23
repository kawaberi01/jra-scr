"""概要: 2026再検証の特徴・全馬確率を予測モジュールなしで独立照合する。
作成日: 2026-11-13。
入力: --run 再検証出力、--dataset 元研究JSON。
出力: run内verification.json。正常0、不一致は例外で非0。
実行例: uv run python scripts/verify_elizabeth_2026_recheck.py --run artifacts/jra_research/elizabeth_2026_recheck_verified --dataset artifacts/jra_research/elizabeth_conditions_v1_20261108_export_v4/dataset.json
注意事項: 標準ライブラリのみ。DB・通信・研究コード呼出しなし。
"""

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path


GROUPS = [["age", "frame"], ["previous_race", "previous_grade", "previous_weight_rule", "previous_symbol"],
          ["previous_rank", "interval"], ["previous_distance", "distance_change", "weight_change"],
          ["repeat_top3", "course_distance_top3", "graded_top3"]]


def features(race: dict, horse: dict, history: list[dict], quality: bool) -> dict:
    """元履歴から既知14特徴を独立定義で再構成する。"""
    result = dict.fromkeys([f for group in GROUPS for f in group])
    result.update(age=str(horse["age"]) if horse["age"] <= 5 else "6歳以上",
                  frame="内1〜3" if horse["frame_no"] <= 3 else "中4〜6" if horse["frame_no"] <= 6 else "外7〜8")
    prior = sorted([h for h in history if h["horse_id"] == horse["horse_id"] and h["race_date"] < race["race_date"]
                    and h["status"] == "active"], key=lambda r: (r["race_date"], r["race_key"]))
    if not prior:
        return result
    p = prior[-1]
    gap = (date.fromisoformat(race["race_date"])-date.fromisoformat(p["race_date"])).days
    result.update(previous_race=p.get("race_name") or None, previous_grade=p.get("grade") or None,
                  previous_weight_rule=p.get("weight_rule") or None, previous_symbol=p.get("symbol") or None,
                  previous_rank=("1〜3着" if p["rank"] <= 3 else "4〜5着" if p["rank"] <= 5 else "6着以下") if p.get("rank") else None,
                  interval="28日以下" if gap <= 28 else "29〜56日" if gap <= 56 else "57日以上",
                  previous_distance="1800m以下" if p["distance"] <= 1800 else "1801〜2000m" if p["distance"] <= 2000 else "2001〜2200m" if p["distance"] <= 2200 else "2201m以上",
                  distance_change="延長" if race["distance"] > p["distance"] else "短縮" if race["distance"] < p["distance"] else "同距離")
    if p.get("weight_carried") is not None:
        delta = horse["weight_carried"]-p["weight_carried"]
        result["weight_change"] = "増" if delta > .01 else "減" if delta < -.01 else "同"
    good = [h for h in prior if h.get("rank") and h["rank"] <= 3]
    result["repeat_top3"] = "確認あり" if any(h["race_name"] == race["race_name"] for h in good) else "確認なし"
    result["course_distance_top3"] = "確認あり" if any(h["venue_code"] == race["venue_code"] and h["distance"] == race["distance"] and int(h["track_code"]) < 23 for h in good) else "確認なし"
    confirmed = all(h.get("conditions_verified", h.get("ra_verified")) is True for h in prior)
    if quality:
        grade = max([{"A": 5, "B": 3, "C": 1}[h["grade"]]+(h["rank"] == 1) for h in good if h.get("grade") in ("A", "B", "C")], default=0)
        result["graded_top3"] = ["確認なし", "GIII2〜3着", "GIII勝利", "GII2〜3着", "GII勝利", "GI2〜3着", "GI勝利"][grade] if grade or confirmed else None
    else:
        result["graded_top3"] = "確認あり" if any(h.get("grade") in ("A", "B", "C") for h in good) else "確認なし" if confirmed else None
    return result


def solve(total_function, target: float, low: float, high: float) -> float:
    """単調増加関数の目標合計を二分法で解く。"""
    for _ in range(150):
        middle = (low+high)/2
        if total_function(middle) > target:
            high = middle
        else:
            low = middle
    return (low+high)/2


def independent_probabilities(dataset: dict, card: dict, history: list[dict], quality: bool) -> dict:
    """条件の分子分母から固定係数で全馬の周辺確率を独立計算する。"""
    observations = []
    for race in dataset["races"]:
        active = [h for h in race["runners"] if h["status"] == "active"]
        if race["race_date"] >= card["race_date"] or sum(bool(h.get("rank") and h["rank"] <= 3) for h in active) != 3:
            continue
        for horse in active:
            observations.append((race["venue_code"], bool(horse.get("rank") and horse["rank"] <= 3), features(race, horse, dataset["history"], quality)))
    overall = sum(r[1] for r in observations)/len(observations)
    local = [r for r in observations if r[0] == card["venue_code"]]
    baseline = (sum(r[1] for r in local)+20*overall)/(len(local)+20)
    logit = lambda p: math.log(max(1e-9, min(1-1e-9, p))/(1-max(1e-9, min(1-1e-9, p))))
    scores = {}
    for horse in card["runners"]:
        values = features(card, horse, history, quality)
        terms = []
        for group in GROUPS:
            effects = []
            for field in group:
                matches = [r for r in observations if values[field] is not None and r[2][field] == values[field]]
                if not matches:
                    continue
                global_rate = (sum(r[1] for r in matches)+20*overall)/(len(matches)+20)
                nearby = [r for r in matches if r[0] == card["venue_code"]]
                rate = (sum(r[1] for r in nearby)+20*global_rate)/(len(nearby)+20)
                effects.append(logit(rate)-logit(baseline))
            terms.append(sum(effects)/len(effects) if effects else 0)
        scores[horse["horse_no"]] = sum(terms)/5*(4 if quality else 1)
    sigmoid = lambda x: 1/(1+math.exp(-x))
    offset = solve(lambda d: sum(sigmoid(s+d) for s in scores.values()), 3, -100, 100)
    return {k: sigmoid(s+offset) for k, s in scores.items()}


def main() -> None:
    """前後2条件の504特徴値・72確率と入力SHAを検査する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    result, dataset = load(args.run / "recheck.json"), load(args.dataset)
    full = load(args.run / "normalized-history.json")
    original = [h for h in full if h.get("source") != "official_profile_and_race_conditions"]
    checks, largest = 0, 0.
    for scope, history in (("before", original), ("after", full)):
        for row in result[scope]["features"]:
            expected = features(result["card"], row, history, True)
            assert expected == row["values"]
            checks += len(expected)
        base = independent_probabilities(dataset, result["card"], history, False)
        candidate = independent_probabilities(dataset, result["card"], history, True)
        clip = lambda key, delta: min(base[key]+.05, 1, max(base[key]-.05, 0, candidate[key]+delta))
        offset = solve(lambda delta: sum(clip(key, delta) for key in base), 3, -1, 1)
        for variant in ("v1", "v2"):
            for row in result[scope][variant]["runners"]:
                expected = base[row["horse_no"]] if variant == "v1" else clip(row["horse_no"], offset)
                diff = abs(row["probability_top3"]-expected)
                assert diff < 1e-11
                largest = max(largest, diff)
    manifest = load(args.run / "manifest.json")
    for name, sha in manifest["input_sha256"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == sha
    for name, sha in manifest["output_sha256"].items():
        assert hashlib.sha256((args.run / name).read_bytes()).hexdigest() == sha
    output = {"status": "passed", "feature_values": checks, "probability_values": 72, "largest_absolute_error": largest,
              "input_and_output_hashes": "passed", "prediction_module_imported": False,
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.run / "verification.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
