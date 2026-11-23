"""概要: 固定した5条件群の全32構成を比較し、過去年だけで選択して翌年を評価する。
作成日: 2026-11-13。
入力: 初版の条件設定と内容SHAを持つ保存済みdataset。
出力: 全構成の確率・指標、時系列選択、安定性診断と参考候補。
実行例: uv run python scripts/run_jra_conditions_search.py --help
注意事項: 後ろ向き研究。DB・通信・購入・既定モデル変更を行わない。
"""

from __future__ import annotations

from collections import Counter
import math
import random

from .jra_race_conditions import aggregate, examples, predict, probabilities, require
from .jra_research_contracts import digest


PROTOCOL = "elizabeth-five-groups-subsets-v1"
MINIMUM_SELECTION_RACES = 5
BOOTSTRAP_REPEATS = 5000
BOOTSTRAP_SEED = 20261113
TOLERANCE = 1e-12


def patterns(config: dict) -> list[dict]:
    """設定順の5群をビット化し、空集合を含む32構成を返す。"""
    groups = list(config["groups"])
    require(len(groups) == 5, "search_requires_five_groups")
    return [{"mask": mask, "pattern": f"P{mask:02d}",
             "groups": [g for i, g in enumerate(groups) if mask & (1 << i)],
             "group_count": mask.bit_count()} for mask in range(32)]


def subset_prediction(full: dict, pattern: dict) -> dict:
    """群の固定係数1/5を保ち、採用部分集合の確率を結果を見ずに再計算する。"""
    active = set(pattern["groups"])
    rows = full["runners"]
    scores = [sum(g["delta"] for g in row["groups"] if g["group"] in active) / 5 for row in rows]
    estimated = probabilities(scores)
    result = [{"horse_no": r["horse_no"], "horse_id": r["horse_id"], "horse_name": r["horse_name"],
               "probability_top3": p} for r, p in zip(rows, estimated, strict=True)]
    result.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return {k: full[k] for k in ("race_key", "race_date", "venue_code", "prior_latest_date", "prior_races")} | {
        "pattern": pattern["pattern"], "mask": pattern["mask"], "groups": pattern["groups"], "runners": result}


def score_prediction(prediction: dict, target: dict) -> dict:
    """二値確率損失と、同率を公平に扱う順位指標を同一出走集合で算出する。"""
    truth = {r["horse_no"]: int(r["outcome"]["top3"]) for r in target["rows"]}
    pairs = [(r["probability_top3"], truth[r["horse_no"]]) for r in prediction["runners"]]
    n = len(pairs)
    capture = 0.0
    hit = 0.0
    start = 0
    while start < n:
        end = start + 1
        while end < n and abs(pairs[end][0] - pairs[start][0]) <= TOLERANCE:
            end += 1
        success = sum(y for _, y in pairs[start:end])
        if start == 0:
            hit = success / (end - start)
        slots = max(0, min(3, end) - start)
        capture += slots * success / (end - start)
        start = end
    return {"races": 1, "runners": n, "brier": sum((p-y)**2 for p, y in pairs) / n,
            "logloss": -sum(y * math.log(max(p, 1e-12)) + (1-y) * math.log(max(1-p, 1e-12))
                            for p, y in pairs) / n,
            "top1_top3_hit": hit, "top3_captured": capture}


def choose_pattern(annual: list[dict], candidates: list[dict]) -> dict:
    """過去検証年のBrier最小を選び、同値なら少数群・番号順を優先する。"""
    require(bool(annual), "search_no_selection_history")
    summaries = {p["pattern"]: aggregate([r for r in annual if r["pattern"] == p["pattern"]])
                 for p in candidates}
    require(all(v["races"] > 0 for v in summaries.values()), "search_incomplete_candidates")
    best = min(v["brier"] for v in summaries.values())
    eligible = [p for p in candidates if summaries[p["pattern"]]["brier"] <= best + TOLERANCE]
    choice = min(eligible, key=lambda p: (p["group_count"], p["mask"]))
    return {**choice, "selection_metric": "runner_weighted_brier", "selection_summary": summaries[choice["pattern"]],
            "candidate_brier": {k: v["brier"] for k, v in summaries.items()}}


def bootstrap_difference(first: list[dict], second: list[dict], repeats: int = BOOTSTRAP_REPEATS) -> dict:
    """同じ開催を対にして復元抽出し、出走行加重Brier差の参考区間を返す。"""
    require(bool(first) and len(first) == len(second), "search_bootstrap_shape")
    require(all(a["race_key"] == b["race_key"] and a["runners"] == b["runners"]
                for a, b in zip(first, second, strict=True)), "search_bootstrap_pairing")
    require(type(repeats) is int and repeats > 0, "search_bootstrap_repeats")
    rng = random.Random(BOOTSTRAP_SEED)
    deltas = []
    for _ in range(repeats):
        indices = rng.choices(range(len(first)), k=len(first))
        total = sum(first[i]["runners"] for i in indices)
        deltas.append(sum((first[i]["brier"] - second[i]["brier"]) * first[i]["runners"]
                          for i in indices) / total)
    deltas.sort()
    low, high = deltas[int(.025*(repeats-1))], deltas[int(.975*(repeats-1))]
    return {"difference": aggregate(first)["brier"] - aggregate(second)["brier"],
            "interval95": [low, high], "includes_zero": low <= 0 <= high,
            "repeats": repeats, "seed": BOOTSTRAP_SEED, "unit": "race", "negative_favors_first": True}


def selection_history(annual: list[dict], candidates: list[dict]) -> list[dict]:
    """過去の検証が5開催揃った年から、その年より前だけで構成を選ぶ。"""
    dates = sorted({r["race_date"] for r in annual})
    result = []
    for day in dates:
        prior = [r for r in annual if r["race_date"] < day]
        if len({r["race_key"] for r in prior}) < MINIMUM_SELECTION_RACES:
            continue
        selected = choose_pattern(prior, candidates)
        current = next(r for r in annual if r["race_date"] == day and r["pattern"] == selected["pattern"])
        result.append({**current, "chosen_groups": selected["groups"], "selection_latest_date": max(r["race_date"] for r in prior),
                       "selection_races": len({r["race_key"] for r in prior}),
                       "selection_brier": selected["selection_summary"]["brier"],
                       "candidate_brier": selected["candidate_brier"]})
    return result


def inspect_subsets(dataset: dict, config: dict, bootstrap_repeats: int = BOOTSTRAP_REPEATS) -> dict:
    """全構成・単独・組合せ・時系列選択・安定性を固定規則で順に精査する。"""
    require(dataset.get("input_sha256") == digest({k: v for k, v in dataset.items() if k != "input_sha256"}),
            "search_dataset_sha")
    require(dataset.get("schema_version") == 1 and dataset.get("race_name") == config["race_name"],
            "search_dataset_contract")
    candidates = patterns(config)
    races = examples(dataset)
    annual, predictions, skipped = [], [], []
    for target in races:
        prior = [r for r in races if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
        if not target["evaluation_eligible"] or len(prior) < config["minimum_prior_races"]:
            skipped.append({"race_key": target["race_key"], "reason": "warmup" if target["evaluation_eligible"] else "top3_count_not_three"})
            continue
        full = predict(prior, target, config)
        for pattern in candidates:
            prediction = subset_prediction(full, pattern)
            predictions.append(prediction)
            annual.append({k: prediction[k] for k in ("pattern", "mask", "race_key", "race_date", "venue_code")} |
                          score_prediction(prediction, target))
    require(bool(annual), "search_no_evaluation_races")
    summary = []
    for pattern in candidates:
        current = [r for r in annual if r["pattern"] == pattern["pattern"]]
        reference = {r["race_key"]: r for r in annual if r["mask"] == 31}
        summary.append({**pattern, "all": aggregate(current),
                        "venues": {v: aggregate([r for r in current if r["venue_code"] == v]) for v in ("08", "09")},
                        "better_than_full_years": sum(r["brier"] < reference[r["race_key"]]["brier"] - TOLERANCE for r in current),
                        "worse_than_full_years": sum(r["brier"] > reference[r["race_key"]]["brier"] + TOLERANCE for r in current)})
    final = choose_pattern(annual, candidates)
    selected = selection_history(annual, candidates)
    outer_days = {r["race_date"] for r in selected}
    comparisons = {"past_selected": selected,
                   "fixed_full": [r for r in annual if r["mask"] == 31 and r["race_date"] in outer_days],
                   "uniform": [r for r in annual if r["mask"] == 0 and r["race_date"] in outer_days]}
    intervals = {name: bootstrap_difference(selected, comparisons[name], bootstrap_repeats)
                 for name in ("fixed_full", "uniform")} if selected else {}
    deleted = []
    for key in sorted({r["race_key"] for r in annual}):
        remaining = [r for r in annual if r["race_key"] != key]
        if remaining:
            winner = choose_pattern(remaining, candidates)
            deleted.append({"omitted_race_key": key, "selected_pattern": winner["pattern"], "groups": winner["groups"]})
    lookup = {p["mask"]: p["all"]["brier"] for p in summary}
    additions = []
    for i, group in enumerate(config["groups"]):
        pairs = [{"without": mask, "with": mask | (1 << i),
                  "brier_difference": lookup[mask | (1 << i)] - lookup[mask]}
                 for mask in range(32) if not mask & (1 << i)]
        additions.append({"group": group, "pairs": pairs, "improved_pairs": sum(p["brier_difference"] < -TOLERANCE for p in pairs),
                          "mean_difference": sum(p["brier_difference"] for p in pairs) / 16})
    best_hit = max(p["all"]["top1_top3_hit"] for p in summary)
    verdict = "insufficient_outer_years" if not selected else (
        "historical_selection_improvement" if all(v["interval95"][1] < 0 for v in intervals.values()) else "advantage_not_established")
    return {"protocol": PROTOCOL, "input_sha256": dataset["input_sha256"], "config_sha256": digest(config),
            "group_weight_denominator": 5, "minimum_selection_races": MINIMUM_SELECTION_RACES,
            "tie_policy": "random_expected_within_1e-12", "patterns": summary, "annual": annual,
            "predictions": predictions, "skipped": skipped,
            "final_research_candidate": final, "best_top1_patterns": [p["pattern"] for p in summary if abs(p["all"]["top1_top3_hit"]-best_hit) <= TOLERANCE],
            "selection": selected, "outer_summary": {k: aggregate(v) for k, v in comparisons.items()},
            "paired_intervals": intervals, "selection_counts": dict(Counter(r["pattern"] for r in selected)),
            "leave_one_race_out": deleted, "addition_diagnostics": additions, "verdict": verdict,
            "limitations": ["後ろ向き研究であり、既使用の過去は完全未知試験ではない。",
                            "最小Brier構成の同期間成績は探索値。候補探索後の区間を採用証明にしない。",
                            "群係数1/5・区切り・縮約は固定。全ての重みや相互作用の最適解ではない。",
                            "過去カードは事後版、前走はDB内直近。市場比較・収益・最新入力は未検証。"]}


def render_search(result: dict) -> str:
    """全構成の順位と、選択後の成績を明確に区別した日本語レポートを返す。"""
    lines = ["# エリザベス女王杯・全32構成の精査", "", "状態: 後ろ向きの研究比較。実用採用・今年の予想ではありません。",
             "", "5条件群の固定係数1/5を保ち、不要群を0にします。残群数で重みを増やしません。",
             "確率は合計3の未校正3着内周辺確率。同確率の順位指標は無作為選択の期待値です。", "",
             "## 1. 全32構成の比較（探索値）", "",
             "| ID | 使用群 | Brier | logloss | 最上位3着内率 | 上位3頭捕捉平均 | 全群より改善/悪化した年 |",
             "|---|---|---:|---:|---:|---:|---|"]
    for p in sorted(result["patterns"], key=lambda p: (p["all"]["brier"], p["group_count"], p["mask"])):
        m = p["all"]
        lines.append(f"| {p['pattern']} | {'＋'.join(p['groups']) or '一律'} | {m['brier']:.6f} | {m['logloss']:.6f} | "
                     f"{m['top1_top3_hit']:.1%} | {m['top3_captured']:.3f} | {p['better_than_full_years']}/{p['worse_than_full_years']} |")
    final = result["final_research_candidate"]
    lines += ["", f"固定選択基準での参考候補: {final['pattern']} {'＋'.join(final['groups']) or '一律'}。",
              "主基準はBrier最小。同値は少数群・ID順です。的中率最大の構成とは別です。",
              f"最上位3着内率が最大の構成: {', '.join(result['best_top1_patterns'])}。これを理由に主基準を変更しません。", "",
              "## 2. 過去の検証年だけで構成を選び翌年へ適用", "",
              "各年の選択は以前の検証5開催以上で行います。3方式は同じ対象年で比較します。", "",
              "| 方式 | 開催数 | 出走行 | Brier | logloss | 最上位3着内率 | 上位3頭捕捉平均 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key, m in result["outer_summary"].items():
        if m["races"]:
            lines.append(f"| {key} | {m['races']} | {m['runners']} | {m['brier']:.6f} | {m['logloss']:.6f} | {m['top1_top3_hit']:.1%} | {m['top3_captured']:.3f} |")
    lines += ["", "| 評価年 | 選択構成 | 使用群 | 選択に使った最終日 | 選択用開催数 | Brier |", "|---|---|---|---|---:|---:|"]
    for row in result["selection"]:
        lines.append(f"| {row['race_date']} | {row['pattern']} | {'＋'.join(row['chosen_groups']) or '一律'} | "
                     f"{row['selection_latest_date']} | {row['selection_races']} | {row['brier']:.6f} |")
    lines += ["", "## 3. 安定性とパーツ追加の診断", ""]
    for key, v in result["paired_intervals"].items():
        lines.append(f"- 過去年選択 − {key}: Brier差 {v['difference']:+.6f}、開催単位bootstrap参考95%区間 "
                     f"[{v['interval95'][0]:+.6f}, {v['interval95'][1]:+.6f}]。負が選択側に有利。")
    for d in result["addition_diagnostics"]:
        lines.append(f"- {d['group']}を足す16対: 改善{d['improved_pairs']}対、平均Brier差{d['mean_difference']:+.6f}。探索診断。")
    count = Counter(r["selected_pattern"] for r in result["leave_one_race_out"])
    lines += [f"- 1開催ずつ除いた探索首位の回数: {dict(count)}。時系列検証ではありません。",
              f"- 判定: {result['verdict']}。", "", "## 制約", ""]
    lines += ["- " + item for item in result["limitations"]]
    return "\n".join(lines) + "\n"
