"""概要: 既知条件の強度・配分・縮約・近年重視を69候補で固定比較する。
作成日: 2026-11-13。
入力: 保存dataset、初版設定、固定した候補一覧。
出力: 全候補予測、仮説群別と全体の時系列選択、採否と診断。
実行例: uv run python scripts/run_jra_conditions_refinement.py --help
注意事項: 後ろ向き研究。DB・外部取得・購入・既定変更なし。
"""

from __future__ import annotations

import math

from .jra_conditions_search import bootstrap_difference, score_prediction
from .jra_race_conditions import aggregate, examples, probabilities, require
from .jra_research_contracts import digest


PROTOCOL = "elizabeth-known-conditions-refinement-v1"
BASELINE = "H1-S1"
UNIFORM = "H1-S0"


def refinement_candidates(config: dict) -> list[dict]:
    """事前仕様の6仮説群69候補を、固定順序と非負配分で生成する。"""
    groups = list(config["groups"])
    require(len(groups) == 5, "refinement_requires_five_groups")
    result = []
    for scale in (0, .5, 1, 2, 4, 8):
        result.append({"pattern": f"H1-S{scale}", "family": "H1", "weights": [1]*5, "scale": scale})
    for mask in range(1, 31):
        result.append({"pattern": f"H2-P{mask:02d}", "family": "H2",
                       "weights": [int(bool(mask & (1 << i))) for i in range(5)], "scale": 1})
    allocations = [[2 if i == focus else 1 for i in range(5)] for focus in range(5)] + [[.5, 2, 2, .5, 1]]
    for index, weights in enumerate(allocations):
        for scale in (1, 2, 4):
            result.append({"pattern": f"H3-W{index}-S{scale}", "family": "H3", "weights": weights, "scale": scale})
    for strength in (5, 80):
        for scale in (1, 2, 4):
            result.append({"pattern": f"H4-K{strength}-S{scale}", "family": "H4", "weights": [1]*5,
                           "scale": scale, "shrinkage": strength})
    for half_life in (5, 10):
        for scale in (1, 2, 4):
            result.append({"pattern": f"H5-T{half_life}-S{scale}", "family": "H5", "weights": [1]*5,
                           "scale": scale, "half_life": half_life})
    for scale in (1, 2, 4):
        result.append({"pattern": f"H6-GLOBAL-S{scale}", "family": "H6", "weights": [1]*5,
                       "scale": scale, "pooling": "global"})
    for order, candidate in enumerate(result):
        candidate.update(order=order, shrinkage=candidate.get("shrinkage", config["shrinkage"]),
                         half_life=candidate.get("half_life"), pooling=candidate.get("pooling", "hierarchical"))
        candidate["groups"] = [g for g, w in zip(groups, candidate["weights"], strict=True) if w > 0 and candidate["scale"] > 0]
        candidate["group_count"] = len(candidate["groups"])
    require(len(result) == 69 and len({c["pattern"] for c in result}) == 69, "refinement_candidate_contract")
    return result


def logit(value: float) -> float:
    """初版と同じ境界保護で率を対数オッズへ変換する。"""
    value = min(1-1e-9, max(1e-9, value))
    return math.log(value/(1-value))


def group_deltas(prior: list[dict], target: dict, config: dict, candidate: dict) -> list[dict]:
    """過去年の加重カテゴリ集計から、各馬の5群差分と根拠を返す。

    Args:
        prior: 評価可能な対象年より前の同名競走。
        target: 事前特徴と、集計で参照しない当該結果を持つ競走。
        config: 初版の特徴群定義。
        candidate: 縮約件数、半減期、開催場共有方式。
    Returns:
        馬番ごとの群差分・観測件数と有効重み。未観測は中立。
    """
    prior = [r for r in prior if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
    require(len(prior) >= config["minimum_prior_races"], "refinement_insufficient_prior")
    half_life = candidate["half_life"]
    observed = [(race, row, 1.0 if half_life is None else 2 ** (-(int(target["race_date"][:4])-int(race["race_date"][:4]))/half_life))
                for race in prior for row in race["rows"]]
    total_weight = sum(w for _, _, w in observed)
    b = sum(w * row["outcome"]["top3"] for _, row, w in observed)/total_weight
    k = candidate["shrinkage"]
    same = [(r, row, w) for r, row, w in observed if r["venue_code"] == target["venue_code"]]
    local_weight = sum(w for _, _, w in same)
    base = b if candidate["pooling"] == "global" else (
        sum(w*row["outcome"]["top3"] for _, row, w in same) + k*b)/(local_weight+k)
    output = []
    for row in target["rows"]:
        deltas, evidence = [], []
        for group, features in config["groups"].items():
            terms, items = [], []
            for feature in features:
                value = row["values"][feature]
                matches = [(r, h, w) for r, h, w in observed if value is not None and h["values"][feature] == value]
                if not matches:
                    continue
                mass = sum(w for _, _, w in matches)
                success = sum(w*h["outcome"]["top3"] for _, h, w in matches)
                global_rate = (success+k*b)/(mass+k)
                local = [(r, h, w) for r, h, w in matches if r["venue_code"] == target["venue_code"]]
                local_mass = sum(w for _, _, w in local)
                local_success = sum(w*h["outcome"]["top3"] for _, h, w in local)
                rate = global_rate if candidate["pooling"] == "global" else (local_success+k*global_rate)/(local_mass+k)
                terms.append(logit(rate)-logit(base))
                items.append({"feature": feature, "value": value, "n": len(matches), "weighted_n": mass,
                              "weighted_top3": success, "same_venue_n": len(local), "same_venue_weight": local_mass,
                              "rate": rate})
            deltas.append(sum(terms)/len(terms) if terms else 0.)
            evidence.append({"group": group, "items": items})
        output.append({"horse_no": row["horse_no"], "horse_id": row["horse_id"], "horse_name": row["horse_name"],
                       "deltas": deltas, "evidence": evidence})
    return output


def candidate_prediction(deltas: list[dict], target: dict, candidate: dict) -> dict:
    """正規化した非負配分と倍率から、合計3の各馬確率を計算する。"""
    weights = candidate["weights"]
    total = sum(weights)
    require(total > 0 and all(w >= 0 and math.isfinite(w) for w in weights)
            and math.isfinite(candidate["scale"]) and candidate["scale"] >= 0, "refinement_weights")
    scores = [candidate["scale"] * sum(w*d for w, d in zip(weights, row["deltas"], strict=True))/total for row in deltas]
    p = probabilities(scores)
    rows = [{k: row[k] for k in ("horse_no", "horse_id", "horse_name")} | {"probability_top3": value}
            for row, value in zip(deltas, p, strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return {"pattern": candidate["pattern"], "family": candidate["family"], "race_key": target["race_key"],
            "race_date": target["race_date"], "venue_code": target["venue_code"], "runners": rows}


def choose_candidate(annual: list[dict], candidates: list[dict]) -> dict:
    """以前の検証Brierを主基準にし、同値なら少数群・固定順で選ぶ。"""
    values = {c["pattern"]: aggregate([r for r in annual if r["pattern"] == c["pattern"]]) for c in candidates}
    require(bool(values) and all(v["races"] for v in values.values()), "refinement_selection_data")
    best = min(v["brier"] for v in values.values())
    selected = min((c for c in candidates if values[c["pattern"]]["brier"] <= best+1e-12),
                   key=lambda c: (c["group_count"], c["order"]))
    return {"candidate": selected, "selection_summary": values[selected["pattern"]],
            "candidate_brier": {k: v["brier"] for k, v in values.items()}}


def qualify(comparison: dict, baseline: dict, interval: dict, improved_years: int) -> bool:
    """仕様050で事前固定した4条件を満たす時だけ有望判定を返す。"""
    return (comparison["brier"] <= .99*baseline["brier"] and interval["interval95"][1] < 0
            and comparison["logloss"] <= baseline["logloss"] and improved_years > comparison["races"]/2)


def refine(dataset: dict, config: dict, repeats: int = 5000) -> dict:
    """69候補を予測し、各仮説と全体の時系列選択・事前基準を評価する。"""
    require(dataset.get("input_sha256") == digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "refinement_dataset_sha")
    require(dataset.get("schema_version") == 1 and dataset.get("race_name") == config["race_name"], "refinement_dataset_contract")
    candidates = refinement_candidates(config)
    races = examples(dataset)
    annual, predictions, evidence = [], [], []
    for target in races:
        prior = [r for r in races if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
        if not target["evaluation_eligible"] or len(prior) < config["minimum_prior_races"]:
            continue
        cache = {}
        for c in candidates:
            key = (c["shrinkage"], c["half_life"], c["pooling"])
            if key not in cache:
                cache[key] = group_deltas(prior, target, config, c)
                evidence.append({"race_key": target["race_key"], "race_date": target["race_date"],
                                 "prior_latest_date": max(r["race_date"] for r in prior),
                                 "shrinkage": key[0], "half_life": key[1], "pooling": key[2], "runners": cache[key]})
            prediction = candidate_prediction(cache[key], target, c)
            predictions.append(prediction)
            annual.append({k: prediction[k] for k in ("pattern", "family", "race_key", "race_date", "venue_code")} |
                          score_prediction(prediction, target))
    require(bool(annual), "refinement_no_evaluation")
    summary = [{**c, "all": aggregate([r for r in annual if r["pattern"] == c["pattern"]]),
                "venues": {v: aggregate([r for r in annual if r["pattern"] == c["pattern"] and r["venue_code"] == v])
                           for v in ("08", "09")}} for c in candidates]
    dates = sorted({r["race_date"] for r in annual})
    scopes = ["H1", "H2", "H3", "H4", "H5", "H6", "all"]
    selection, outer = [], {}
    for scope in scopes:
        pool = candidates if scope == "all" else [c for c in candidates if c["family"] == scope or c["pattern"] == BASELINE]
        selected = []
        for day in dates:
            past = [r for r in annual if r["race_date"] < day and any(c["pattern"] == r["pattern"] for c in pool)]
            if len({r["race_key"] for r in past}) < 5:
                continue
            choice = choose_candidate(past, pool)
            c = choice["candidate"]
            current = next(r for r in annual if r["race_date"] == day and r["pattern"] == c["pattern"])
            selected.append({**current, "scope": scope, "selection_latest_date": max(r["race_date"] for r in past),
                             "selection_races": len({r["race_key"] for r in past}), "candidate_brier": choice["candidate_brier"]})
        days = {r["race_date"] for r in selected}
        fixed = [r for r in annual if r["pattern"] == BASELINE and r["race_date"] in days]
        uniform = [r for r in annual if r["pattern"] == UNIFORM and r["race_date"] in days]
        if selected:
            interval = bootstrap_difference(selected, fixed, repeats)
            wins = sum(a["brier"] < b["brier"]-1e-12 for a, b in zip(selected, fixed, strict=True))
            m, b = aggregate(selected), aggregate(fixed)
            outer[scope] = {"selected": m, "baseline": b, "uniform": aggregate(uniform),
                            "relative_brier_improvement": 1-m["brier"]/b["brier"], "improved_years": wins,
                            "vs_baseline": interval, "vs_uniform": bootstrap_difference(selected, uniform, repeats),
                            "qualifies": qualify(m, b, interval, wins),
                            "final_candidate": choose_candidate(annual, pool)}
        selection.extend(selected)
    return {"protocol": PROTOCOL, "candidates": candidates, "summary": summary, "annual": annual,
            "predictions": predictions, "evidence": evidence, "selection": selection, "outer": outer,
            "final_research_candidate": choose_candidate(annual, candidates),
            "input_sha256": dataset["input_sha256"], "config_sha256": digest(config),
            "verdict": "promising_research_candidate" if outer.get("all", {}).get("qualifies") else "criterion_not_met",
            "limitations": ["仮説は既使用の過去から提案。時系列評価も後ろ向きで、独立未知試験ではない。",
                            "69候補は6仮説の有限比較。候補間全交差・新特徴・市場・収益・今年の入力は未検証。",
                            "開催単位bootstrapは少数年・年の依存・研究全体の多重比較を解消しない。",
                            "履歴は保存内直近、過去カードは事後版。結果で記事公開時点を証明しない。"]}


def render_refinement(result: dict) -> str:
    """探索首位と過去年選択の成績・採否を分けたレポートを生成する。"""
    lines = ["# エリザベス女王杯・6仮説69候補の固定比較", "", f"判定: {result['verdict']}。研究候補の判定で、本番採用ではありません。",
             "", "主基準は3着内Brier。旧方式比1%以上改善・差の参考95%区間上端<0・logloss非悪化・過半数年改善を事前条件としました。",
             "各年の選択は以前の検証5開催以上だけで行い、同率順位は期待値です。", "",
             "## 仮説別の翌年適用比較", "", "| 範囲 | 開催 | Brier | 旧方式比改善 | logloss | 最上位3着内率 | 改善年 | 差の95%参考区間 | 条件通過 |",
             "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for scope, row in result["outer"].items():
        m, ci = row["selected"], row["vs_baseline"]["interval95"]
        lines.append(f"| {scope} | {m['races']} | {m['brier']:.6f} | {row['relative_brier_improvement']:.2%} | "
                     f"{m['logloss']:.6f} | {m['top1_top3_hit']:.1%} | {row['improved_years']} | [{ci[0]:+.6f}, {ci[1]:+.6f}] | {row['qualifies']} |")
    if result["outer"]:
        baseline = next(iter(result["outer"].values()))
        lines += ["", f"同期間の旧全5群: Brier {baseline['baseline']['brier']:.6f}、logloss {baseline['baseline']['logloss']:.6f}。",
                  f"同期間の一律: Brier {baseline['uniform']['brier']:.6f}、logloss {baseline['uniform']['logloss']:.6f}。"]
    lines += ["", "## 全期間の上位候補（探索値）", "", "| ID | 仮説 | 配分 | 倍率 | 縮約 | 半減期 | 共有 | Brier | logloss | 最上位3着内率 |",
              "|---|---|---|---:|---:|---|---|---:|---:|---:|"]
    for c in sorted(result["summary"], key=lambda c: c["all"]["brier"]):
        m = c["all"]
        lines.append(f"| {c['pattern']} | {c['family']} | {c['weights']} | {c['scale']} | {c['shrinkage']} | {c['half_life']} | {c['pooling']} | "
                     f"{m['brier']:.6f} | {m['logloss']:.6f} | {m['top1_top3_hit']:.1%} |")
    c = result["final_research_candidate"]["candidate"]
    lines += ["", f"全過去年から選んだ次回参考設定: {c['pattern']}。この設定の同期間成績は探索値です。", "",
              "## 全候補からの年別選択", "", "| 評価日 | 選択ID | 選択に使った最終日 | Brier |", "|---|---|---|---:|"]
    for row in result["selection"]:
        if row["scope"] == "all":
            lines.append(f"| {row['race_date']} | {row['pattern']} | {row['selection_latest_date']} | {row['brier']:.6f} |")
    lines += ["", "## 制約", "", *["- "+v for v in result["limitations"]]]
    return "\n".join(lines)+"\n"
