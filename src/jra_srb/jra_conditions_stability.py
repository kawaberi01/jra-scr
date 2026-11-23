"""概要: 保存済み69候補から混合・平均・保守選択・変動制限の8仮説を比較する。
作成日: 2026-11-13。
入力: 先行比較の保存予測・年度指標・候補と、元dataset。
出力: 8安定化方式と2基準の全予測・時系列選択・採否。
実行例: uv run python scripts/run_jra_conditions_stability.py --help
注意事項: 過去を再利用する追加研究。未来結果・DB・外部情報は使わない。
"""

from __future__ import annotations

from statistics import stdev
import math

from .jra_conditions_refinement import BASELINE, choose_candidate, qualify
from .jra_conditions_search import bootstrap_difference, score_prediction
from .jra_race_conditions import aggregate, examples, require
from .jra_research_contracts import digest


POLICIES = ["baseline", "selected69", "mix25", "mix50", "mix75", "ensemble3", "ensemble5", "one_se", "cap05", "cap10"]


def bounded_probabilities(chosen: list[float], baseline: list[float], cap: float) -> list[float]:
    """旧確率からの最大変動と0〜1を守り、合計3へ共通切片で射影する。"""
    require(len(chosen) == len(baseline) and 0 < cap <= 1, "stability_cap_shape")
    bounds = [(max(0., b-cap), min(1., b+cap)) for b in baseline]
    lo, hi = -1., 1.
    for _ in range(100):
        mid = (lo+hi)/2
        total = sum(min(upper, max(lower, p+mid)) for p, (lower, upper) in zip(chosen, bounds, strict=True))
        if total < 3:
            lo = mid
        else:
            hi = mid
    return [min(upper, max(lower, p+(lo+hi)/2)) for p, (lower, upper) in zip(chosen, bounds, strict=True)]


def conservative_choice(past: list[dict], candidates: list[dict], prediction_lookup: dict) -> dict:
    """開催差の1標準誤差以内で、過去予測が旧方式に最も近い候補を選ぶ。"""
    choice = choose_candidate(past, candidates)["candidate"]
    dates = sorted({r["race_date"] for r in past})
    metric = {(r["race_date"], r["pattern"]): r for r in past}
    eligible = []
    for candidate in candidates:
        differences = [metric[(day, candidate["pattern"])]["brier"]-metric[(day, choice["pattern"])]["brier"] for day in dates]
        se = stdev(differences)/math.sqrt(len(differences)) if len(differences) > 1 else 0.
        if sum(differences)/len(differences) > se+1e-12:
            continue
        squared, count = 0., 0
        for day in dates:
            old = {r["horse_no"]: r["probability_top3"] for r in prediction_lookup[(day, BASELINE)]["runners"]}
            for row in prediction_lookup[(day, candidate["pattern"])]["runners"]:
                squared += (row["probability_top3"]-old[row["horse_no"]])**2
                count += 1
        eligible.append((squared/count, candidate["group_count"], candidate["order"], candidate))
    require(bool(eligible), "stability_no_conservative_candidate")
    return min(eligible, key=lambda item: item[:3])[3]


def build_policies(day: str, annual: list[dict], candidates: list[dict], lookup: dict) -> list[dict]:
    """当該より前の成績だけで部品候補を選び、固定8変換と2基準を生成する。"""
    past = [r for r in annual if r["race_date"] < day]
    require(len({r["race_key"] for r in past}) >= 5, "stability_selection_warmup")
    choice = choose_candidate(past, candidates)
    selected = choice["candidate"]["pattern"]
    conservative = conservative_choice(past, candidates, lookup)["pattern"]
    ranked = sorted(candidates, key=lambda c: (choice["candidate_brier"][c["pattern"]], c["group_count"], c["order"]))
    base = lookup[(day, BASELINE)]
    numbers = [r["horse_no"] for r in base["runners"]]
    maps = {c["pattern"]: {r["horse_no"]: r["probability_top3"] for r in lookup[(day, c["pattern"])]["runners"]}
            for c in candidates}
    original = [maps[BASELINE][n] for n in numbers]
    best = [maps[selected][n] for n in numbers]
    values = {"baseline": original, "selected69": best}
    components = {"baseline": [BASELINE], "selected69": [selected]}
    for label, ratio in (("mix25", .25), ("mix50", .5), ("mix75", .75)):
        values[label] = [(1-ratio)*b+ratio*p for b, p in zip(original, best, strict=True)]
        components[label] = [BASELINE, selected]
    for size in (3, 5):
        label = "ensemble"+str(size)
        components[label] = [c["pattern"] for c in ranked[:size]]
        values[label] = [sum(maps[c][n] for c in components[label])/size for n in numbers]
    values["one_se"] = [maps[conservative][n] for n in numbers]
    components["one_se"] = [conservative]
    for label, cap in (("cap05", .05), ("cap10", .10)):
        values[label] = bounded_probabilities(best, original, cap)
        components[label] = [BASELINE, selected]
    output = []
    for label in POLICIES:
        rows = [{k: row[k] for k in ("horse_no", "horse_id", "horse_name")} | {"probability_top3": p}
                for row, p in zip(base["runners"], values[label], strict=True)]
        rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
        output.append({"pattern": label, "race_date": day, "race_key": base["race_key"], "venue_code": base["venue_code"],
                       "selection_latest_date": max(r["race_date"] for r in past), "components": components[label], "runners": rows})
    return output


def stabilize(source: dict, dataset: dict, repeats: int = 5000) -> dict:
    """固定8変換を同じ13開催で比較し、さらに過去だけで方式を選ぶ副検証を行う。"""
    require(dataset["input_sha256"] == source["input_sha256"], "stability_source_dataset")
    require(dataset["input_sha256"] == digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "stability_dataset_sha")
    annual = source["annual"]
    candidates = source["candidates"]
    lookup = {(p["race_date"], p["pattern"]): p for p in source["predictions"]}
    targets = {r["race_date"]: r for r in examples(dataset)}
    metrics, predictions = [], []
    for day in sorted({r["race_date"] for r in annual}):
        if len({r["race_key"] for r in annual if r["race_date"] < day}) < 5:
            continue
        for prediction in build_policies(day, annual, candidates, lookup):
            predictions.append(prediction)
            metrics.append({k: prediction[k] for k in ("pattern", "race_date", "race_key", "venue_code")} |
                           score_prediction(prediction, targets[day]))
    baseline = [r for r in metrics if r["pattern"] == "baseline"]
    require(bool(baseline), "stability_no_outer_years")
    summary = {}
    for label in POLICIES:
        rows = [r for r in metrics if r["pattern"] == label]
        interval = bootstrap_difference(rows, baseline, repeats)
        improved = sum(a["brier"] < b["brier"]-1e-12 for a, b in zip(rows, baseline, strict=True))
        m = aggregate(rows)
        summary[label] = {"all": m, "vs_baseline": interval, "improved_years": improved,
                          "relative_improvement": 1-m["brier"]/aggregate(baseline)["brier"],
                          "qualifies": qualify(m, aggregate(baseline), interval, improved),
                          "venues": {v: aggregate([r for r in rows if r["venue_code"] == v]) for v in ("08", "09")}}
    selected = []
    for day in sorted({r["race_date"] for r in metrics}):
        past = [r for r in metrics if r["race_date"] < day]
        if len({r["race_key"] for r in past}) < 5:
            continue
        scores = {label: aggregate([r for r in past if r["pattern"] == label])["brier"] for label in POLICIES}
        minimum = min(scores.values())
        winner = next(label for label in POLICIES if scores[label] <= minimum+1e-12)
        current = next(r for r in metrics if r["race_date"] == day and r["pattern"] == winner)
        selected.append({**current, "selection_latest_date": max(r["race_date"] for r in past), "candidate_brier": scores})
    days = {r["race_date"] for r in selected}
    matching = [r for r in baseline if r["race_date"] in days]
    meta = {"selected": aggregate(selected), "baseline": aggregate(matching),
            "interval": bootstrap_difference(selected, matching, repeats) if selected else None}
    return {"protocol": "elizabeth-refinement-stabilization-v1", "input_sha256": dataset["input_sha256"],
            "summary": summary, "annual": metrics, "predictions": predictions, "policy_selection": selected,
            "meta": meta, "qualifying_policies": [p for p in POLICIES if summary[p]["qualifies"]],
            "limitations": ["先行結果から提案した追加探索であり、未知試験ではない。",
                            "13開催の方式別比較と、過去だけで方式を選ぶ8開催比較を区別する。",
                            "事前採用条件を維持し、良かった方式だけの事後選択を事前成績と呼ばない。"]}


def render_stability(result: dict) -> str:
    """安定化の各固定方式と追加の時系列選択を区別して報告する。"""
    lines = ["# 改善候補の安定化・8仮説の比較", "", "条件通過: "+str(result["qualifying_policies"]), "",
             "| 方式 | 開催 | Brier | 旧方式比改善 | logloss | 最上位3着内率 | 改善年 | 差の参考95%区間 | 通過 |",
             "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for label, row in result["summary"].items():
        m = row["all"]
        ci = row["vs_baseline"]["interval95"]
        lines.append(f"| {label} | {m['races']} | {m['brier']:.6f} | {row['relative_improvement']:.2%} | {m['logloss']:.6f} | "
                     f"{m['top1_top3_hit']:.1%} | {row['improved_years']} | [{ci[0]:+.6f}, {ci[1]:+.6f}] | {row['qualifies']} |")
    lines += ["", "## 過去5開催から安定化方式を選ぶ副検証", "", json_text(result["meta"]), "", "## 制約", ""]
    lines += ["- "+v for v in result["limitations"]]
    return "\n".join(lines)+"\n"


def json_text(value: dict) -> str:
    """入れ子の検証指標をJSONコードブロックで表示する。"""
    import json
    return "```json\n"+json.dumps(value, ensure_ascii=False, indent=2)+"\n```"
