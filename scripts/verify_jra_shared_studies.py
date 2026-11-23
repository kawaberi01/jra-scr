"""概要: 共通条件共有と市場選抜の保存値を、原成績・価格・払戻から独立検算する。
作成日: 2026-11-15
入力: --forecast、--output、新しい2研究と元データ成果物。
出力: 検算件数と事前保存・全頭表・仮想予算・SHA確認のJSON。
実行例: uv run python scripts/verify_jra_shared_studies.py --forecast artifacts/jra_research/elizabeth_live_20261115_reviewed_v2 --output artifacts/jra_research/verification-shared-20261115.json
注意事項: 外部通信・DB更新・2026結果参照なし。予測関数や候補選択関数を呼ばない。
"""

import argparse
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path

from evaluate_graded_ticket_market import numeric

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/jra_research"


def read(path):
    """保存されたUTF-8 JSONを読む。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    """集計・選抜・券・価格と凍結表示を独立計算して一致時だけ保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    races={r["race_key"]:r for folder in ("elizabeth_conditions_v1_20261108_export_v4","graded_patterns_20261114_export_v2")
           for r in read(BASE/folder/"dataset.json")["races"]}
    old={(p["series_id"],p["race_key"],p["pattern"]):p for p in read(BASE/"graded_patterns_20261114_verified/predictions.json")}
    shared_dir=BASE/"shared_parts_20261115_analysis"
    plan_dir=BASE/"plan_consensus_20261115_analysis"
    annual=read(shared_dir/"annual.json")
    metrics={(r["series_id"],r["mask"],r["race_key"]):r for r in annual}
    probabilities=0
    for p in read(shared_dir/"predictions.json"):
        assert p["shared_latest_year"]<p["race_date"][:4] and p["own_latest_date"]<p["race_date"]
        truth={r["horse_no"]:int(r["rank"] is not None and r["rank"]<=3) for r in races[p["race_key"]]["runners"] if r["status"]=="active"}
        ref={r["horse_no"]:r["probability_top3"] for r in old[(p["series_id"],p["race_key"],"balanced")]["runners"]}
        ps=p["runners"]
        assert len(ps)==len(truth) and abs(sum(r["probability_top3"] for r in ps)-3)<1e-9
        br,ll=0.,0.
        for r in ps:
            q=r["probability_top3"];y=truth[r["horse_no"]]
            assert abs(q-ref[r["horse_no"]])<=.050000001
            br+=(q-y)**2/len(ps)
            q=max(1e-12,min(1-1e-12,q));ll-=math.log(q if y else 1-q)/len(ps)
        m=metrics[(p["series_id"],p["mask"],p["race_key"])]
        assert abs(br-m["brier"])<1e-12 and abs(ll-m["logloss"])<1e-12
        if p["mask"]==0:
            expected={r["horse_no"]:r["probability_top3"] for r in old[(p["series_id"],p["race_key"],"frozen_v2")]["runners"]}
            assert max(abs(r["probability_top3"]-expected[r["horse_no"]]) for r in ps)<1e-12
        probabilities+=len(ps)
    selection_count=0
    for policy in read(shared_dir/"summary.json")["policies"].values():
        for row in policy["selected_rows"]:
            past=[r for r in annual if r["series_id"]==row["series_id"] and r["race_date"]<row["race_date"]]
            values={m:sum(r["brier"]*r["runners"] for r in past if r["mask"]==m)/sum(r["runners"] for r in past if r["mask"]==m) for m in range(4)}
            chosen=min((m for m in values if values[m]<=min(values.values())+1e-12),key=lambda m:(m.bit_count(),m))
            assert row["mask"]==chosen and row["selection_latest_date"]<row["race_date"]
            selection_count+=1
    quotes={r["race_key"]:{h[0]:q for h,q in numeric(r,1).items()} for r in read(BASE/"graded_tickets_20261114_market_audit/market.json")["rows"] if r["market"]=="win"}
    plans=read(plan_dir/"annual.json")
    for row in plans:
        model=old[(row["series_id"],row["race_key"],"frozen_v2")]["runners"]
        quote=quotes[row["race_key"]]
        popularity=sorted(quote,key=lambda n:(quote[n],n))
        ordered=sorted(model,key=lambda r:(-r["probability_top3"],int(r["horse_no"])))
        name=row["policy"]
        limit=len(quote) if name=="original" else max(3,math.ceil(len(quote)/(2 if name=="half" else 3)))
        expected=popularity[:3] if name=="market" else [int(r["horse_no"]) for r in ordered if int(r["horse_no"]) in set(popularity[:limit])][:3]
        assert row["selected_horses"]==expected
        truth={int(r["horse_no"]) for r in races[row["race_key"]]["runners"] if r["rank"] is not None and r["rank"]<=3}
        assert row["captured"]==len(set(expected)&truth)
    for policy in read(plan_dir/"summary.json")["policies"].values():
        for row in policy["selected_rows"]:
            past=[r for r in plans if r["series_id"]==row["series_id"] and r["race_date"]<row["race_date"]]
            score={p:sum(r["captured"] for r in past if r["policy"]==p)/sum(r["policy"]==p for r in past) for p in ("original","half","third","market")}
            chosen=next(p for p in score if score[p]>=max(score.values())-1e-12)
            assert row["policy"]==chosen and row["selection_latest_date"]<row["race_date"]
            selection_count+=1
    paid={}
    for r in read(BASE/"graded_tickets_20261114_audit/coverage.json")["payouts"]:
        if r["slot_status"]=="published" and r["market"] in ("wide","trio"):
            raw=r["selection_raw"];key=tuple(sorted(int(raw[i:i+2]) for i in range(0,len(raw),2)))
            paid[(r["race_key"],r["market"],key)]=r["payout_yen"]
    tickets=0
    for row in annual+plans:
        assert len(row["tickets"])==4 and sum(t["amount"] for t in row["tickets"])==400
        for t in row["tickets"]:
            assert t["payout_yen"]==paid.get((row["race_key"],t["bet_type"],tuple(t["selection"])),0)
            tickets+=1
        assert row["payout_yen"]==sum(t["payout_yen"] for t in row["tickets"])
    checked_files=0
    for folder in (shared_dir,plan_dir,args.forecast):
        manifest=read(folder/"manifest.json")
        for file,expected in manifest["files"].items():
            assert hashlib.sha256(Path(file).read_bytes()).hexdigest()==expected,file
            checked_files+=1
    p=read(args.forecast/"prediction.json")
    assert p["generated_before_result"] and p["outcome_reads"]==0 and p["purchase_yen"]==0
    assert len(p["forecast"]["runners"])==18 and p["presentation"].count("\n## ")==10
    assert (args.forecast/"presentation.md").read_text(encoding="utf-8")==p["presentation"]
    for plan in [p["condition_parts_plan"],*p["condition_parts_alternatives"]]:
        assert sum(t["amount"] for t in plan["tickets"])==400
        for t in plan["tickets"]:
            source=[r for r in p["odds"]["odds"][t["bet_type"]] if sorted(map(int,r["combination"]))==list(map(int,t["selection"]))]
            assert len(source)==1 and source[0]==t["observed_odds"]
    result=dict(probability_predictions=len(annual),horse_probabilities=probabilities,plan_selections=len(plans),
                temporal_choices=selection_count,settled_tickets=tickets,manifest_files=checked_files,forecast_runners=18,
                template_sections=10,main_virtual_yen=400,comparison_virtual_yen=400,actual_purchase_yen=0,outcome_reads=0)
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print(result)


if __name__=="__main__":
    main()
