"""概要: 直近3走の安定性と前年同レース成績の2部品を4候補で検証する。
作成日: 2026-11-15
入力: 保存済み三系列dataset・v2予測・5群設定。
出力: 新規出力先へ全候補予測・指標・過去年選択・採否。
実行例: uv run python scripts/run_jra_form_parts.py --output artifacts/jra_research/form-parts
注意事項: 外部通信・DB更新なし。2026結果や正規化2年資料を当該年入力へ使わない。
"""

import argparse
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from run_jra_miss_refinement import predict
from jra_srb.jra_graded_patterns import build_examples
from jra_srb.jra_race_conditions import aggregate,load_config
from jra_srb.jra_conditions_search import score_prediction,bootstrap_difference
from jra_srb.jra_conditions_refinement import qualify

BASE=ROOT/"artifacts/jra_research"


def read(path):
    """保存JSONをUTF-8で取得する。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def form_values(race,horse,history):
    """対象日前の国内実出走だけから直近3率と前年同名着順を返す。"""
    prior=sorted([h for h in history if h["horse_id"]==horse["horse_id"] and h["race_date"]<race["race_date"]
                  and h["status"]=="active"],key=lambda h:(h["race_date"],h["race_key"]))
    recent=prior[-3:]
    known=[h for h in recent if h.get("rank") is not None]
    if len(known)!=len(recent) or not recent:
        form=None
    else:
        numerator=sum(h["rank"]<=3 for h in recent)
        form="2/3以上" if numerator*3>=2*len(recent) else "1/3以上" if numerator*3>=len(recent) else "1/3未満"
    year=int(race["race_date"][:4])-1
    previous=[h for h in prior if int(h["race_date"][:4])==year and h.get("race_name")==race["race_name"]]
    if previous:
        assert len(previous)==1
        rank=previous[0].get("rank")
        repeat="1〜3着" if rank and rank<=3 else "4〜6着" if rank and rank<=6 else "7着以下" if rank else None
    else:repeat="前年出走確認なし"
    return dict(recent_three_top3=form,previous_edition_rank=repeat)


def add_parts(races,history,mask):
    """既存の5群特徴を保持したまま指定した部品だけを追加する。"""
    output=deepcopy(races)
    for race in output:
        for horse in race["rows"]:
            values=form_values(race,horse,history)
            for bit,key in ((1,"recent_three_top3"),(2,"previous_edition_rank")):
                if mask&bit:horse["values"][key]=values[key]
    return output


def part_config(config,mask):
    """直近群と過去実績群へ部品を加え、他の係数を保持する。"""
    output=deepcopy(config)
    groups=list(output["groups"])
    assert len(groups)==5
    if mask&1:output["groups"][groups[2]].append("recent_three_top3")
    if mask&2:output["groups"][groups[4]].append("previous_edition_rank")
    return output


def choose(rows):
    """過去検証誤差が最小の候補を選び、同値は追加部品を少なくする。"""
    values={mask:aggregate([r for r in rows if r["mask"]==mask])["brier"] for mask in range(4)}
    minimum=min(values.values())
    return min((mask for mask in values if values[mask]<=minimum+1e-12),key=lambda mask:(mask.bit_count(),mask))


def main():
    """4候補を54開催で評価し、事前基準に従い採否を保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();assert not args.output.exists();args.output.mkdir(parents=True)
    extra=read(BASE/"graded_patterns_20261114_export_v2/dataset.json")
    datasets={"elizabeth":read(BASE/"elizabeth_conditions_v1_20261108_export_v4/dataset.json"),
              **{s:dict(races=[r for r in extra["races"] if r["series_id"]==s],history=extra["history"]) for s in ("musashino","daily2")}}
    old=read(BASE/"graded_patterns_20261114_verified/predictions.json")
    saved={(p["series_id"],p["race_key"],p["pattern"]):p for p in old}
    config=load_config(ROOT/"configs/research/race_conditions_elizabeth_v1.json")
    annual,predictions=[],[];maxerror=0.
    for series,data in datasets.items():
        original=build_examples(data,True)
        for mask in range(4):
            races=add_parts(original,data["history"],mask)
            for i,target in enumerate(races):
                if i<5 or not target["evaluation_eligible"]:continue
                baseline=saved[(series,target["race_key"],"balanced")]
                p=predict(races[:i],target,baseline,part_config(config,mask),0)
                p.update(mask=mask,series_id=series,pattern="F"+str(mask))
                if mask==0:
                    reference={r["horse_no"]:r["probability_top3"] for r in saved[(series,target["race_key"],"frozen_v2")]["runners"]}
                    maxerror=max(maxerror,max(abs(r["probability_top3"]-reference[r["horse_no"]]) for r in p["runners"]))
                predictions.append(p)
                annual.append(dict(series_id=series,mask=mask,race_key=target["race_key"],race_date=target["race_date"],**score_prediction(p,target)))
    assert maxerror<1e-12
    summary={s:{str(mask):aggregate([r for r in annual if r["series_id"]==s and r["mask"]==mask]) for mask in range(4)} for s in datasets}
    policies={}
    for series in datasets:
        rows=[r for r in annual if r["series_id"]==series];selected=[];baseline=[]
        for day in sorted({r["race_date"] for r in rows}):
            past=[r for r in rows if r["race_date"]<day]
            if len({r["race_date"] for r in past})<5:continue
            mask=choose(past)
            selected.append({**next(r for r in rows if r["race_date"]==day and r["mask"]==mask),
                             "selection_latest_date":max(r["race_date"] for r in past)})
            baseline.append(next(r for r in rows if r["race_date"]==day and r["mask"]==0))
        a,b=aggregate(selected),aggregate(baseline);interval=bootstrap_difference(selected,baseline)
        wins=sum(x["brier"]<y["brier"]-1e-12 for x,y in zip(selected,baseline,strict=True))
        policies[series]=dict(selected=a,baseline=b,relative_improvement=1-a["brier"]/b["brier"],interval=interval,
                              improved_years=wins,qualifies=qualify(a,b,interval,wins),final_mask=choose(rows),selected_rows=selected)
    result=dict(summary=summary,policies=policies,baseline_max_error=maxerror,official_2024_2025_used_in_historical_inputs=False,
                outcome_2026_read=False,adoption="eligible_research_candidate" if policies["elizabeth"]["qualifies"] else "keep_frozen_v2")
    for name,value in (("summary",result),("annual",annual),("predictions",predictions)):
        (args.output/(name+".json")).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({s:{k:v for k,v in p.items() if k!="selected_rows"} for s,p in policies.items()},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
