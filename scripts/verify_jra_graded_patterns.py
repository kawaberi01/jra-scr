"""概要: 三重賞の全確率・指標・系列外選択を独立計算で照合する。
作成日: 2026-11-14。
入力: --run 比較出力、--additional 追加dataset、--elizabeth 既存dataset。
出力: run/verification.json。合格0、不一致は例外で非0。
実行例: uv run python scripts/verify_jra_graded_patterns.py --help
注意事項: 予測モジュール・DB・外部通信を使用しない。
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from verify_elizabeth_2026_recheck import features, solve, GROUPS


PATTERNS = {"route": [1, 2], "aptitude": [3, 4], "attributes": [0, 2, 3], "balanced": list(range(5)), "frozen_v2": list(range(5))}


def values(race: dict, horse: dict, history: list[dict], quality: bool) -> dict:
    """既存独立検算の特徴を再利用し、芝ダート一致を独立に補う。"""
    output = features(race, horse, history, quality)
    prior = [h for h in history if h["horse_id"] == horse["horse_id"] and h["race_date"] < race["race_date"] and h["status"] == "active"]
    if prior:
        good = [h for h in prior if h.get("rank") and h["rank"] <= 3]
        output["course_distance_top3"] = "確認あり" if any(h["venue_code"] == race["venue_code"] and h["distance"] == race["distance"] and (int(h["track_code"]) < 23) == (int(race["track_code"]) < 23) for h in good) else "確認なし"
    return output


def deltas(observations: list, target: dict, feature_rows: list) -> list:
    """縮約したカテゴリ率から5群の差分を独立計算する。"""
    global_base = sum(row[1] for row in observations)/len(observations)
    local = [r for r in observations if r[0] == target["venue_code"]]
    base = (sum(r[1] for r in local)+20*global_base)/(len(local)+20)
    def logit(value):
        """率の対数オッズを安定に求める。"""
        p = max(1e-9, min(1-1e-9, value))
        return math.log(p/(1-p))
    result = []
    for values_row in feature_rows:
        groups = []
        for group in GROUPS:
            effects = []
            for f in group:
                matches = [r for r in observations if values_row[f] is not None and r[2][f] == values_row[f]]
                if not matches:
                    continue
                global_rate = (sum(r[1] for r in matches)+20*global_base)/(len(matches)+20)
                nearby = [r for r in matches if r[0] == target["venue_code"]]
                rate = (sum(r[1] for r in nearby)+20*global_rate)/(len(nearby)+20)
                effects.append(logit(rate)-logit(base))
            groups.append(sum(effects)/len(effects) if effects else 0)
        result.append(groups)
    return result


def probability(group_deltas: list, groups: list, scale: int) -> list:
    """任意の固定群配分から合計3の周辺値を独立計算する。"""
    scores = [scale*sum(d[i] for i in groups)/len(groups) for d in group_deltas]
    sigmoid = lambda x: 1/(1+math.exp(-x))
    offset = solve(lambda value: sum(sigmoid(s+value) for s in scores), 3, -100, 100)
    return [sigmoid(s+offset) for s in scores]


def metrics(rows: list, truth: dict) -> dict:
    """損失・同率期待値の順位指標を独立計算する。"""
    pairs = sorted([(p, truth[number]) for number, p in rows], reverse=True)
    hit, capture, start = 0., 0., 0
    while start < len(pairs):
        end = start+1
        while end < len(pairs) and abs(pairs[end][0]-pairs[start][0]) <= 1e-12:
            end += 1
        success = sum(v[1] for v in pairs[start:end])/(end-start)
        if start == 0:
            hit = success
        capture += max(0, min(3, end)-start)*success
        start = end
    return {"brier": sum((p-y)**2 for p, y in pairs)/len(pairs),
            "logloss": -sum(y*math.log(max(p, 1e-12))+(1-y)*math.log(max(1-p, 1e-12)) for p, y in pairs)/len(pairs),
            "top1_top3_hit": hit, "top3_captured": capture}


def selected_pattern(pool: list) -> str:
    """系列均等の一律比損失で4候補を独立に選ぶ。"""
    results = {}
    for name in list(PATTERNS)[:4]:
        skills = []
        for s in sorted({r["series_id"] for r in pool}):
            current = [r for r in pool if r["series_id"] == s and r["pattern"] == name]
            base = [r for r in pool if r["series_id"] == s and r["pattern"] == "uniform"]
            current_loss = sum(r["brier"]*r["runners"] for r in current)/sum(r["runners"] for r in current)
            base_loss = sum(r["brier"]*r["runners"] for r in base)/sum(r["runners"] for r in base)
            skills.append(1-current_loss/base_loss)
        results[name] = sum(skills)/len(skills)
    best = max(results.values())
    return min((p for p in results if results[p] >= best-1e-12), key=lambda p: (len(PATTERNS[p]), p))


def main() -> None:
    """元datasetから全予測を再計算し、保存値・選択境界・SHAを確認する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--additional", type=Path, required=True)
    parser.add_argument("--elizabeth", type=Path, required=True)
    args = parser.parse_args()
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    additional = load(args.additional)
    datasets = {"elizabeth": load(args.elizabeth)}
    for s in ("musashino", "daily2"):
        datasets[s] = {"races": [r for r in additional["races"] if r["series_id"] == s], "history": additional["history"]}
    stored = {(r["series_id"], r["race_key"], r["pattern"]): r for r in load(args.run / "predictions.json")}
    annual = load(args.run / "annual.json")
    probability_count, metric_count, max_error = 0, 0, 0.
    for s, dataset in datasets.items():
        cache, past = {}, []
        for race in sorted(dataset["races"], key=lambda r: r["race_date"]):
            horses = [h for h in race["runners"] if h["status"] == "active"]
            truth = {h["horse_no"]: int(bool(h.get("rank") and h["rank"] <= 3)) for h in horses}
            current = {quality: [values(race, h, dataset["history"], quality) for h in horses] for quality in (False, True)}
            eligible = sum(truth.values()) == 3
            if len(past) >= 5 and eligible:
                obs = {q: [(old["venue_code"], label, v) for old in past for label, v in cache[(old["race_key"], q)]] for q in (False, True)}
                d = {q: deltas(obs[q], race, current[q]) for q in (False, True)}
                expected = {p: probability(d[False], groups, 1) for p, groups in list(PATTERNS.items())[:4]}
                base = expected["balanced"]
                raw = probability(d[True], list(range(5)), 4)
                clipped = lambda i, shift: min(1, base[i]+.05, max(0, base[i]-.05, raw[i]+shift))
                offset = solve(lambda shift: sum(clipped(i, shift) for i in range(len(base))), 3, -1, 1)
                expected["frozen_v2"] = [clipped(i, offset) for i in range(len(base))]
                expected["uniform"] = [3/len(horses)]*len(horses)
                for pattern, probs in expected.items():
                    prediction = stored[(s, race["race_key"], pattern)]
                    by_no = {r["horse_no"]: r["probability_top3"] for r in prediction["runners"]}
                    for horse, p in zip(horses, probs):
                        error = abs(by_no[horse["horse_no"]]-p)
                        assert error < 1e-11
                        max_error = max(max_error, error); probability_count += 1
                    m = metrics([(h["horse_no"], p) for h, p in zip(horses, probs)], truth)
                    saved = next(r for r in annual if r["series_id"] == s and r["race_key"] == race["race_key"] and r["pattern"] == pattern)
                    for key, value in m.items():
                        assert abs(value-saved[key]) < 1e-11
                        metric_count += 1
            for q in (False, True):
                cache[(race["race_key"], q)] = [(truth[h["horse_no"]], v) for h, v in zip(horses, current[q])]
            if eligible:
                past.append(race)
    selection = load(args.run / "selection.json")
    for row in selection:
        pool = [r for r in annual if r["race_date"][:4] < row["race_date"][:4] and r["series_id"] in row["selection_series"]]
        assert row["selected_pattern"] == selected_pattern(pool)
        assert row["selection_latest_year"] < row["race_date"][:4]
        if row["policy"] == "other_series":
            assert row["series_id"] not in row["selection_series"]
    manifest = load(args.run / "manifest.json")
    for path, sha in manifest["inputs"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((args.run / name).read_bytes()).hexdigest() == sha
    output = {"status": "passed", "probability_values": probability_count, "metric_values": metric_count,
              "selection_rows": len(selection), "maximum_probability_error": max_error, "hashes": "passed",
              "prediction_modules_imported": False, "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.run / "verification.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
