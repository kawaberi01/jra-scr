"""概要: 固定v2の馬評価を維持し、市場との合意による候補選抜4規則を検証する。
作成日: 2026-11-15
入力: --output、保存済み予測・T30単勝・成績・公式払戻。
出力: 年別全選択・精算・前年以前だけの選抜・主案変更の採否。
実行例: uv run python scripts/run_jra_plan_consensus.py --output artifacts/jra_research/plan_consensus_20261115_analysis
注意事項: 外部通信・DB更新・2026結果参照・確率変更・実購入なし。
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import random

from run_jra_miss_refinement import ROOT, BASE, read
from evaluate_graded_ticket_market import numeric
from evaluate_graded_ticket_baseline import selection
from run_jra_shared_parts import money, settle
from run_jra_graded_live import table

POLICIES = ("original", "half", "third", "market")


def select_horses(runners, quotes, policy):
    """全出走馬の価格集合を照合し、固定規則の3頭を返す。"""
    assert policy in POLICIES
    numbers = {int(r["horse_no"]) for r in runners}
    assert len(numbers) == len(runners) and set(quotes) == numbers
    assert all(math.isfinite(float(q)) and float(q)>=1 for q in quotes.values())
    market = sorted(numbers, key=lambda n:(float(quotes[n]), n))
    ordered = sorted(runners, key=lambda r:(-r["probability_top3"], int(r["horse_no"])))
    if policy == "market":
        return market[:3]
    limit = len(numbers) if policy == "original" else max(3, math.ceil(len(numbers)/(2 if policy == "half" else 3)))
    eligible = set(market[:limit])
    selected = [int(r["horse_no"]) for r in ordered if int(r["horse_no"]) in eligible][:3]
    assert len(selected) == 3
    return selected


def choose(rows, allow_original=True):
    """以前の捕捉数だけで規則を選び、同値は固定順で解決する。"""
    policies = POLICIES if allow_original else POLICIES[1:]
    score = {p:sum(r["captured"] for r in rows if r["policy"] == p)/sum(r["policy"] == p for r in rows) for p in policies}
    best = max(score.values())
    return next(p for p in policies if score[p] >= best-1e-12)


def capture_interval(selected, baseline, repeats=5000):
    """開催対応差の再抽出で捕捉差の参考区間を計算する。"""
    assert [r["race_key"] for r in selected] == [r["race_key"] for r in baseline]
    differences = [a["captured"]-b["captured"] for a,b in zip(selected,baseline,strict=True)]
    rng = random.Random(20261115)
    samples = sorted(sum(rng.choices(differences,k=len(differences)))/len(differences) for _ in range(repeats))
    return dict(difference=sum(differences)/len(differences), interval95=[samples[int(.025*(repeats-1))],samples[int(.975*(repeats-1))]],
                repeats=repeats, seed=20261115, unit="race", positive_favors_selected=True)


def main():
    """4規則を54開催へ適用し、時系列の実用採否を新規保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    paths=[BASE/"graded_patterns_20261114_verified/predictions.json", BASE/"graded_patterns_20261114_export_v2/dataset.json",
           BASE/"elizabeth_conditions_v1_20261108_export_v4/dataset.json",BASE/"graded_tickets_20261114_market_audit/market.json",
           BASE/"graded_tickets_20261114_audit/coverage.json"]
    old,extra,eliza,market,audit=map(read,paths)
    races={r["race_key"]:r for data in (extra,eliza) for r in data["races"]}
    quotes={r["race_key"]:{h[0]:v for h,v in numeric(r,1).items()} for r in market["rows"] if r["market"] == "win"}
    payouts={}
    for row in audit["payouts"]:
        if row["slot_status"] == "published" and row["market"] in ("wide","trio"):
            payouts.setdefault((row["race_key"],row["market"]),{})[selection(row["selection_raw"],3 if row["market"] == "trio" else 2)]=row["payout_yen"]
    annual=[]
    for prediction in old:
        if prediction["pattern"] != "frozen_v2":
            continue
        key=prediction["race_key"]
        truth={int(r["horse_no"]) for r in races[key]["runners"] if r["rank"] is not None and r["rank"]<=3 and r["status"] == "active"}
        assert len(truth)==3
        for policy in POLICIES:
            selected=select_horses(prediction["runners"],quotes[key],policy)
            byno={int(r["horse_no"]):r for r in prediction["runners"]}
            cash=settle({**prediction,"runners":[byno[n] for n in selected]},payouts)
            annual.append(dict(series_id=prediction["series_id"],race_key=key,race_date=prediction["race_date"],policy=policy,
                               selected_horses=selected,captured=len(set(selected)&truth),**cash))
    policies={}
    for series in ("elizabeth","musashino","daily2"):
        rows=[r for r in annual if r["series_id"]==series]
        chosen,baseline=[],[]
        for day in sorted({r["race_date"] for r in rows}):
            past=[r for r in rows if r["race_date"]<day]
            if len({r["race_date"] for r in past})<5:
                continue
            policy=choose(past)
            chosen.append({**next(r for r in rows if r["race_date"]==day and r["policy"]==policy),"selection_latest_date":max(r["race_date"] for r in past)})
            baseline.append(next(r for r in rows if r["race_date"]==day and r["policy"]=="original"))
        cash,basecash=money(chosen),money(baseline)
        ci=capture_interval(chosen,baseline)
        ok=ci["difference"]>0 and ci["interval95"][0]>0 and cash["return_rate"]>=basecash["return_rate"] and cash["return_rate_without_largest"]>=basecash["return_rate_without_largest"]
        policies[series]=dict(selected_capture=sum(r["captured"] for r in chosen),baseline_capture=sum(r["captured"] for r in baseline),interval=ci,
                              selected_money=cash,baseline_money=basecash,qualifies=ok,final_policy=choose(rows),
                              comparison_policy=choose(rows,False),selected_rows=chosen,
                              fixed={p:{**money([r for r in rows if r["policy"]==p]),"capture":sum(r["captured"] for r in rows if r["policy"]==p)} for p in POLICIES})
    summary=dict(policies=policies,adoption="eligible_consensus_plan" if policies["elizabeth"]["qualifies"] else "keep_original_plan",
                 probabilities_changed=False,outcome_2026_read=False)
    args.output.mkdir(parents=True)
    for name,value in (("summary",summary),("annual",annual)):
        with (args.output/(name+".json")).open("x",encoding="utf-8") as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
    text="# 市場合意による買い目選抜の検証\n\n"+table(["系列","捕捉：基準→案","WT回収：基準→案","捕捉差95%参考区間","主案変更可否","次回参考規則"],
        [[s,f"{p['baseline_capture']}→{p['selected_capture']}",f"{p['baseline_money']['return_rate']:.2%}→{p['selected_money']['return_rate']:.2%}",p["interval"]["interval95"],p["qualifies"],p["final_policy"]] for s,p in policies.items()])
    text+="\n\n4規則を216選抜で比較。13評価年の候補選択は前年以前だけの捕捉数を用い、払戻は選抜に未使用。最大払戻1開催を除いた成績も保存。確率・印は変更しない。基準未達時の比較案は非採用・主案に非合算。\n"
    (args.output/"report.md").write_text(text,encoding="utf-8")
    sources=paths+[Path(__file__),ROOT/"scripts/run_jra_shared_parts.py"]+sorted(args.output.glob("*"))
    (args.output/"manifest.json").write_text(json.dumps(dict(files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}),ensure_ascii=False,indent=2),encoding="utf-8")
    print(text)


if __name__=="__main__":
    main()
