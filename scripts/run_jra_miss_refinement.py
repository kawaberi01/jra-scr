"""概要: 二重賞の保存予想を診断し、頭数・間隔・前走着順の8仮説を比較する。
作成日: 2026-11-15
入力: 保存済み3系列dataset、2結果・事前予想、女王杯11/13参考入力。
出力: 指定した新規フォルダーへ全予測・指標・選択・参考適用・manifest。
実行例: uv run python scripts/run_jra_miss_refinement.py --output artifacts/jra_research/miss-refinement
注意事項: 外部通信・DB更新なし。2026女王杯結果は取得/使用しない。
"""

import argparse
from copy import deepcopy
from datetime import date
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jra_srb.jra_graded_patterns import build_examples
from jra_srb.jra_race_conditions import aggregate, load_config, public_runner
from jra_srb.jra_conditions_refinement import group_deltas, candidate_prediction, qualify
from jra_srb.jra_conditions_search import score_prediction, bootstrap_difference
from jra_srb.jra_conditions_stability import bounded_probabilities

BASE = ROOT / "artifacts/jra_research"
CANDIDATE = dict(pattern="frozen_v2", family="miss_refinement", weights=[1]*5,
                 scale=4, shrinkage=20, half_life=None, pooling="hierarchical")


def read(path):
    """保存済みUTF-8 JSONを読む。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def gap_category(days):
    """実日数を事前固定した5間隔へ分類する。"""
    return ("28日以下" if days <= 28 else "29〜56日" if days <= 56 else "57〜90日" if days <= 90
            else "91〜149日" if days <= 149 else "150日以上")


def transform(races, history, mask):
    """結果領域を変更せず対象日前の直近国内走から特徴の粒度を変える。"""
    result = deepcopy(races)
    indexed = {}
    for h in history:
        if h["status"] == "active":
            indexed.setdefault(h["horse_id"], []).append(h)
    for race in result:
        for row in race["rows"]:
            prior = [h for h in indexed.get(row["horse_id"], []) if h["race_date"] < race["race_date"]]
            if not prior:
                continue
            previous = max(prior, key=lambda h: (h["race_date"], h["race_key"]))
            if mask & 2:
                days = (date.fromisoformat(race["race_date"])-date.fromisoformat(previous["race_date"])).days
                row["values"]["interval"] = gap_category(days)
            rank = previous.get("rank")
            if mask & 4 and rank and rank <= 3:
                row["values"]["previous_rank"] = "1着" if rank == 1 else "2〜3着"
    return result


def logit(value):
    """有限な対数オッズを返す。"""
    value = max(1e-12, min(1-1e-12, value))
    return math.log(value/(1-value))


def adjusted_deltas(prior, target, config, mask):
    """既存の条件率に対応する無作為期待率を同じ階層縮約で計算する。"""
    evidence = group_deltas(prior, target, config, CANDIDATE)
    if not mask & 1:
        return evidence
    observed = [(race, row) for race in prior if race["evaluation_eligible"] and race["race_date"] < target["race_date"]
                for row in race["rows"]]
    b = sum(row["outcome"]["top3"] for race, row in observed)/len(observed)
    k = CANDIDATE["shrinkage"]
    for horse in evidence:
        deltas = []
        for group in horse["evidence"]:
            terms = []
            for item in group["items"]:
                matches = [(race, row) for race, row in observed if row["values"][item["feature"]] == item["value"]]
                expected = (sum(3/len(race["rows"]) for race, row in matches)+k*b)/(len(matches)+k)
                local = [(race, row) for race, row in matches if race["venue_code"] == target["venue_code"]]
                expected = (sum(3/len(race["rows"]) for race, row in local)+k*expected)/(len(local)+k)
                item["expected_rate"] = expected
                terms.append(logit(item["rate"])-logit(expected))
            deltas.append(sum(terms)/len(terms) if terms else 0.)
        horse["deltas"] = deltas
    return evidence


def predict(prior, target, baseline, config, mask):
    """仮説の確率を元balanced比±5ptへ制限し、旧v2を保持する。"""
    evidence = adjusted_deltas(prior, target, config, mask)
    prediction = candidate_prediction(evidence, target, {**CANDIDATE, "pattern": "M"+str(mask)})
    reference = {r["horse_no"]: r["probability_top3"] for r in baseline["runners"]}
    p = bounded_probabilities([r["probability_top3"] for r in prediction["runners"]],
                              [reference[r["horse_no"]] for r in prediction["runners"]], .05)
    prediction["runners"] = sorted([{**r, "probability_top3": value} for r, value in zip(prediction["runners"], p, strict=True)],
                                    key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return prediction


def choose(annual):
    """結果が確定した過去検証集合だけで候補を選び、同値時は変更を少なくする。"""
    means = {mask: aggregate([r for r in annual if r["mask"] == mask])["brier"] for mask in range(8)}
    best = min(means.values())
    return min((mask for mask in means if means[mask] <= best+1e-12), key=lambda m: (m.bit_count(), m))


def miss_audit():
    """事前の最終2予想を保存結果で精算し、馬評価と仮想収支を分離する。"""
    output = []
    for series in ("musashino", "daily2"):
        folder = BASE / ("graded_live_20261114_"+series+"_forecast_v3")
        forecast = read(folder/"prediction.json")
        assert hashlib.sha256((folder/"prediction.json").read_bytes()).hexdigest() == read(folder/"manifest.json")["prediction_sha256"]
        result = read(BASE/"graded_misses_20261115_inputs"/(series+"-result.json"))
        truth = {str(r["horse_no"]).zfill(2): int(r["rank"]) for r in result["results"] if str(r["rank"]).isdigit()}
        target = dict(rows=[dict(horse_no=h, outcome=dict(top3=rank<=3)) for h, rank in truth.items()])
        metrics = score_prediction(forecast["forecast"], target)
        paid = {}
        for row in result["payouts"]:
            if row["bet_type"] not in ("ワイド", "3連複"):
                continue
            key = tuple(sorted(int(h) for h in row["combination"].split("-")))
            paid[("wide" if row["bet_type"] == "ワイド" else "trio", key)] = int(row["payout"].replace(",", ""))
        top = sorted(int(h) for h, rank in truth.items() if rank <= 3)
        assert len(top) == 3
        assert {k for (m,k) in paid if m == "wide"} == set(combinations(top, 2))
        assert {k for (m,k) in paid if m == "trio"} == {tuple(top)}
        bets = [{**t, "payout_yen": paid.get((t["bet_type"], tuple(sorted(int(h) for h in t["selection"]))), 0)*t["amount"]//100}
                for t in forecast["condition_parts_plan"]["tickets"]]
        rows = [{**h, "actual_rank": truth[h["horse_no"]]} for h in forecast["forecast"]["runners"]]
        output.append(dict(series_id=series, artifact_id=forecast["artifact_id"], actual_top3=top, metrics=metrics,
                           uniform_brier=(3/len(rows))*(1-3/len(rows)), runners=rows, tickets=bets,
                           virtual_stake_yen=sum(t["amount"] for t in bets), virtual_payout_yen=sum(t["payout_yen"] for t in bets)))
    return output


def main():
    """8候補の過去時系列比較と保存入力への感度を新規成果物へまとめる。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "output_exists"
    args.output.mkdir(parents=True)
    config = load_config(ROOT/"configs/research/race_conditions_elizabeth_v1.json")
    extra = read(BASE/"graded_patterns_20261114_export_v2/dataset.json")
    datasets = {"elizabeth": read(BASE/"elizabeth_conditions_v1_20261108_export_v4/dataset.json"),
                **{s: dict(races=[r for r in extra["races"] if r["series_id"] == s], history=extra["history"])
                   for s in ("musashino", "daily2")}}
    previous = read(BASE/"graded_patterns_20261114_verified/predictions.json")
    saved = {(p["series_id"],p["race_key"],p["pattern"]):p for p in previous}
    predictions, annual, contexts = [], [], {}
    max_error = 0.
    for series, dataset in datasets.items():
        originals = build_examples(dataset)
        resolved = build_examples(dataset, True)
        variants = {bits: transform(resolved, dataset["history"], bits) for bits in (0, 2, 4, 6)}
        contexts[series] = variants
        for i, original in enumerate(originals):
            if i < 5 or not original["evaluation_eligible"]:
                continue
            baseline = saved[(series, original["race_key"], "balanced")]
            for mask in range(8):
                races = variants[mask & 6]
                target = races[i]
                p = predict(races[:i], target, baseline, config, mask)
                p.update(series_id=series, mask=mask)
                if mask == 0:
                    old = {r["horse_no"]:r["probability_top3"] for r in saved[(series, original["race_key"], "frozen_v2")]["runners"]}
                    max_error = max(max_error, max(abs(r["probability_top3"]-old[r["horse_no"]]) for r in p["runners"]))
                predictions.append(p)
                annual.append(dict(series_id=series, mask=mask, race_key=target["race_key"], race_date=target["race_date"], **score_prediction(p,target)))
    assert max_error < 1e-12, "baseline_reproduction_failed"
    summary = {series:{str(mask):aggregate([r for r in annual if r["series_id"] == series and r["mask"] == mask])
                       for mask in range(8)} for series in datasets}
    policies = {}
    for series in datasets:
        rows = [r for r in annual if r["series_id"] == series]
        selected, baseline = [], []
        for day in sorted({r["race_date"] for r in rows}):
            past = [r for r in rows if r["race_date"] < day]
            if len({r["race_date"] for r in past}) < 5:
                continue
            mask = choose(past)
            selected.append({**next(r for r in rows if r["race_date"] == day and r["mask"] == mask),
                             "selection_latest_date": max(r["race_date"] for r in past)})
            baseline.append(next(r for r in rows if r["race_date"] == day and r["mask"] == 0))
        comparison = aggregate(selected)
        reference = aggregate(baseline)
        interval = bootstrap_difference(selected, baseline)
        wins = sum(a["brier"]<b["brier"]-1e-12 for a,b in zip(selected,baseline,strict=True))
        policies[series] = dict(selected=comparison, baseline=reference, selected_rows=selected,
                                relative_improvement=1-comparison["brier"]/reference["brier"], improved_years=wins,
                                interval=interval, qualifies=qualify(comparison,reference,interval,wins), final_mask=choose(rows))
    eliza = read(BASE/"elizabeth_2026_recheck_final/recheck.json")
    history = read(BASE/"elizabeth_2026_recheck_final/normalized-history.json")
    card = eliza["card"]
    after = eliza["after"]
    target = {**{k:v for k,v in card.items() if k != "runners"}, "rows": [
        {**public_runner(r), "values":next(h["values"] for h in after["features"] if h["horse_no"] == r["horse_no"])} for r in card["runners"]]}
    current = []
    for mask in range(8):
        t = transform([target],history,mask)[0]
        p = predict(contexts["elizabeth"][mask & 6],t,after["v1"],config,mask)
        current.append(dict(mask=mask, observed_card_at=card["observed_at"], reference_only=True, prediction=p))
    output = dict(summary=summary, policies=policies, misses=miss_audit(), baseline_max_error=max_error,
                  adoption="eligible_research_candidate" if policies["elizabeth"]["qualifies"] else "keep_frozen_v2",
                  result_2026_used_for_selection=False, elizabeth_2026_result_read=False)
    for name, value in (("summary",output),("predictions",predictions),("annual",annual),("elizabeth_reference",current)):
        (args.output/(name+".json")).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in output.items() if k not in ("summary","misses")},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
