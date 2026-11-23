"""概要: 固定v2とT30単勝からの市場参考確率を5混合比で時系列比較する。
作成日: 2026-11-15
入力: 保存済み予想・dataset・T30市場・HR払戻。
出力: 新規保存先へ全確率・指標・選択・固定買い目精算。
実行例: uv run python scripts/run_jra_market_assistance.py --output artifacts/jra_research/market-assistance
注意事項: 外部通信・DB更新なし。市場確率は順次抽出の仮定付き。2026結果は選択に不使用。
"""

import argparse
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from evaluate_graded_ticket_market import numeric
from evaluate_graded_ticket_baseline import selection, summarize
from jra_srb.jra_conditions_search import score_prediction, bootstrap_difference
from jra_srb.jra_conditions_refinement import qualify
from jra_srb.jra_race_conditions import aggregate

BASE = ROOT/"artifacts/jra_research"
ALPHAS = (0., .25, .5, .75, 1.)


def read(path):
    """保存JSONをUTF-8で読む。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def market_top3(weights):
    """順次抽出モデルの1/2/3着全順序を厳密合算した馬別周辺値を返す。

    Args:
        weights: 正の重み。単勝倍率逆数を想定する。
    Returns:
        元の順序に対応した3着内の参考確率。合計3。
    Raises:
        ValueError: 頭数不足または非正の重みの場合。
    """
    import math
    if len(weights) < 4 or any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError("invalid_market_weights")
    total = sum(weights)
    w = [v/total for v in weights]
    result = []
    for i, own in enumerate(w):
        p = own
        for j, first in enumerate(w):
            if j == i:
                continue
            p += first*own/(1-first)
            for k, second in enumerate(w):
                if k != i and k != j:
                    p += first*second*own/((1-first)*(1-first-second))
        result.append(p)
    assert abs(sum(result)-3)<1e-9 and all(0<=p<=1 for p in result)
    return result


def blend(core, market, alpha):
    """同じ馬順の2周辺確率を固定係数で混合する。"""
    assert len(core) == len(market) and alpha in ALPHAS
    result = [(1-alpha)*a+alpha*b for a,b in zip(core,market,strict=True)]
    assert abs(sum(result)-3)<1e-9
    return result


def choose(rows):
    """渡された過去検証だけでBrier最小の混合比を選ぶ。"""
    means = {alpha:aggregate([r for r in rows if r["alpha"]==alpha])["brier"] for alpha in ALPHAS}
    minimum = min(means.values())
    return min(a for a in ALPHAS if means[a] <= minimum+1e-12)


def main():
    """54開催の固定5混合比と、系列ごとの過去選択を比較して保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    args.output.mkdir(parents=True)
    sources=["graded_patterns_20261114_verified/predictions.json", "graded_patterns_20261114_export_v2/dataset.json",
             "elizabeth_conditions_v1_20261108_export_v4/dataset.json", "graded_tickets_20261114_market_audit/market.json",
             "graded_tickets_20261114_audit/coverage.json"]
    saved,extra,eliza,market,audit=[read(BASE/p) for p in sources]
    races={r["race_key"]:r for d in (extra,eliza) for r in d["races"]}
    quotes={r["race_key"]:numeric(r,1) for r in market["rows"] if r["market"]=="win"}
    hr={}
    for row in audit["payouts"]:
        if row["slot_status"]=="published" and row["market"] in ("wide","trio","quinella"):
            hr.setdefault((row["race_key"],row["market"]),{})[selection(row["selection_raw"],3 if row["market"]=="trio" else 2)]=row["payout_yen"]
    annual,predictions,ledger=[],[],[]
    for original in saved:
        if original["pattern"]!="frozen_v2":
            continue
        key=original["race_key"]
        rows=original["runners"]
        numbers=[int(r["horse_no"]) for r in rows]
        assert {h[0] for h in quotes[key]}==set(numbers)
        core=[r["probability_top3"] for r in rows]
        proxy=market_top3([1/quotes[key][(n,)] for n in numbers])
        target=dict(rows=[dict(horse_no=r["horse_no"],outcome=dict(top3=bool(r.get("rank") and r["rank"]<=3)))
                          for r in races[key]["runners"] if r["status"]=="active"])
        for alpha in ALPHAS:
            probabilities=blend(core,proxy,alpha)
            runners=sorted([{**r,"probability_top3":p} for r,p in zip(rows,probabilities,strict=True)],
                           key=lambda r:(-r["probability_top3"],int(r["horse_no"])))
            prediction={**original,"runners":runners,"alpha":alpha,"pattern":"A"+str(alpha)}
            predictions.append(prediction)
            annual.append(dict(series_id=original["series_id"],race_key=key,race_date=original["race_date"],
                               alpha=alpha,**score_prediction(prediction,target)))
            selected=sorted(int(r["horse_no"]) for r in runners[:3])
            bets={m:[dict(market=m,horses=list(c),stake_yen=100,payout_yen=hr[(key,m)].get(c,0))
                     for c in combinations(selected,3 if m=="trio" else 2)] for m in ("wide","trio","quinella")}
            for kind,items in (("W3",bets["wide"]),("T1",bets["trio"]),("Q3",bets["quinella"]),("WT",bets["wide"]+bets["trio"])):
                ledger.append(dict(pattern="A"+str(alpha),alpha=alpha,series_id=original["series_id"],race_key=key,policy=kind,
                                   tickets=items,stake_yen=100*len(items),payout_yen=sum(t["payout_yen"] for t in items)))
    summaries={series:{str(alpha):aggregate([r for r in annual if r["series_id"]==series and r["alpha"]==alpha])
                       for alpha in ALPHAS} for series in ("elizabeth","musashino","daily2")}
    policies={}
    for series in summaries:
        rows=[r for r in annual if r["series_id"]==series]
        selected,baseline=[],[]
        for day in sorted({r["race_date"] for r in rows}):
            past=[r for r in rows if r["race_date"]<day]
            if len({r["race_date"] for r in past})<5:
                continue
            alpha=choose(past)
            selected.append({**next(r for r in rows if r["race_date"]==day and r["alpha"]==alpha),
                             "selection_latest_date":max(r["race_date"] for r in past)})
            baseline.append(next(r for r in rows if r["race_date"]==day and r["alpha"]==0))
        a,b=aggregate(selected),aggregate(baseline)
        interval=bootstrap_difference(selected,baseline)
        wins=sum(x["brier"]<y["brier"]-1e-12 for x,y in zip(selected,baseline,strict=True))
        policies[series]=dict(selected=a,baseline=b,relative_improvement=1-a["brier"]/b["brier"],improved_years=wins,
                              interval=interval,qualifies=qualify(a,b,interval,wins),selected_rows=selected,final_alpha=choose(rows))
    result=dict(summary=summaries,policies=policies,ticket_summary=summarize(ledger),
                model_assumption="sequential_sampling_without_replacement_from_inverse_win_odds",
                result_2026_used_for_selection=False,elizabeth_2026_result_read=False,
                inputs={p:hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in sources})
    for name,value in (("summary",result),("annual",annual),("predictions",predictions),("ledger",ledger)):
        (args.output/(name+".json")).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({s:{k:v for k,v in p.items() if k!="selected_rows"} for s,p in policies.items()},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
