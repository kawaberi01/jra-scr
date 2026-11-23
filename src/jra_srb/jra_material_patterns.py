"""概要: 公式成績の直近近距離GI時計差と同一レース内末脚を既存マイル予想へ比較追加する。
作成日: 2026-11-22
入力: SHA照合済み公式成績、恒久ID対応、保存履歴と既存予測。
出力: P/Fの事前特徴・根拠、4方式の確率、開発選択と参照確認。
実行例: uv run python scripts/run_jra_material_patterns.py --help
注意事項: 探索的研究。封印snapshot入力や利益の実証ではなく、未来結果を使わない。
"""

from collections import defaultdict
from datetime import date,timedelta
import math
import re

from .jra_race_conditions import require,probabilities
from .jra_conditions_refinement import group_deltas
from .jra_specific_patterns import metrics,mean_metrics
from .jra_head_to_head import compare

GROUPS={"時計差":["g1_gap"],"末脚":["g1_final3f"]}
OPTIONS=(("baseline",()),("baseline+P",(0,)),("baseline+F",(1,)),("baseline+P+F",(0,1)))


def number(value):
    """有限な数値をfloatへ変換し、欠測と不正値をNoneにする。"""
    if value is None:return None
    result=float(value)
    return result if math.isfinite(result) else None


def measures(own: dict,field: list[dict]) -> dict:
    """同一競走内の時計差と、80%充足時の同着平均末脚順位を計算する。"""
    v=own["values"]; completed=[r for r in field if type(r["values"].get("finish_rank")) is int and r["values"]["finish_rank"]>0]
    own_time=number(v.get("finish_time_seconds")); winner=[number(r["values"].get("finish_time_seconds")) for r in completed if r["values"]["finish_rank"]==1]
    winner=[t for t in winner if t is not None and t>0]
    gap=None
    if v.get("finish_rank") and own_time is not None and own_time>0 and winner:
        gap=own_time-min(winner)
        require(gap>=-.001,"material_negative_gap")
        gap=max(0.,gap)
    known=[number(r["values"].get("final_3f_seconds")) for r in completed]
    known=[t for t in known if t is not None and t>0]
    own_final=number(v.get("final_3f_seconds")); percentile=None
    if v.get("finish_rank") and completed and len(known)/len(completed)>=.8 and own_final is not None and own_final>0:
        lower=sum(t<own_final-1e-9 for t in known); equal=sum(abs(t-own_final)<=1e-9 for t in known)
        percentile=(lower+(equal+1)/2)/len(known)
    return {"gap_seconds":gap,"final3f_percentile":percentile,"finish_time_seconds":own_time,
            "winner_time_seconds":min(winner) if winner else None,"final_3f_seconds":own_final,
            "completed_count":len(completed),"final3f_known_count":len(known)}


def feature(race: dict,runner: dict,history: list[dict],facts: list[dict],links: list[dict],foreign: list[dict]) -> dict:
    """当該日前730日以内の最新芝1400〜1800m国際GIを先に選び、欠測で古い走へ戻らない。"""
    start=(date.fromisoformat(race["race_date"])-timedelta(days=730)).isoformat()
    candidates=[h for h in history if h["horse_id"]==runner["horse_id"] and start<=h["race_date"]<race["race_date"] and
                h["status"]=="active" and h.get("grade")=="A" and 1400<=h["distance"]<=1800 and 10<=int(h["track_code"])<=22]
    candidates += [{**h,"race_key":f"nonJRA:{h['horse_id']}:{h['race_date']}","foreign":True} for h in foreign if
        h["horse_id"]==runner["horse_id"] and start<=h["race_date"]<race["race_date"] and h.get("international_grade_raw")=="GI" and h["surface_raw"]=="芝" and 1400<=h["distance"]<=1800]
    if not candidates:return {"values":{"g1_gap":None,"g1_final3f":None},"reason":"no_confirmed_prior_near_GI","previous":None}
    previous=max(candidates,key=lambda h:(h["race_date"],h["race_key"]))
    measured={"gap_seconds":None,"final3f_percentile":None}
    record=None
    if previous.get("foreign"):
        # 公式の勝利と自馬時計が共に確認できる場合、自分自身との差0だけが判定可能。
        cells=previous.get("source_row_cells",[])
        parsed=re.fullmatch(r"(\d+):(\d{2})\.(\d+)",str(cells[11])) if len(cells)>11 else None
        known_time=bool(parsed and int(parsed[2])<60 and (int(parsed[1])>0 or int(parsed[2])>0 or int(parsed[3])>0))
        if previous.get("rank")==1 and known_time:measured["gap_seconds"]=0.
    else:
        matched=[r for r in links if r["race_key"]==previous["race_key"] and r["horse_id"]==runner["horse_id"]]
        require(len(matched)<=1,"material_duplicate_link")
        if matched:
            selected=[f for f in facts if f["record_id"]==matched[0]["record_id"]]
            require(len(selected)==1,"material_link_fact_missing")
            record=selected[0]; measured=measures(record,[f for f in facts if f["race_key"]==previous["race_key"]])
    gap,late=measured["gap_seconds"],measured["final3f_percentile"]
    values={"g1_gap":None if gap is None else "同時計（表示精度内）" if gap<=.001 else "0.5秒以内" if gap<=.500001 else "1秒以内" if gap<=1.000001 else "1秒超",
            "g1_final3f":None if late is None else "上位1/3" if late<=1/3+1e-9 else "中位1/3" if late<=2/3+1e-9 else "下位1/3"}
    return {"values":values,"previous":{k:previous.get(k) for k in ("race_key","race_date","race_name","race_name_raw","rank","foreign")},
            "measures":measured,"record_id":record["record_id"] if record else None,"fields":record["fields"] if record else {},
            "reason":"official_nonJRA_limited" if previous.get("foreign") else "matched_official_record" if record else "official_record_unavailable"}


def combine(base: dict,evidence: list[dict],pattern: str,indices: tuple) -> dict:
    """保存基準のlogitへP/F各0.5の群差分を追加し、欠測は差分0とする。"""
    if not indices:return {**base,"pattern":pattern}
    delta={r["horse_id"]:sum(r["deltas"][i] for i in indices) for r in evidence}
    scores=[math.log(r["probability_top3"]/(1-r["probability_top3"]))+.5*delta[r["horse_id"]] for r in base["runners"]]
    rows=[{**r,"probability_top3":p} for r,p in zip(base["runners"],probabilities(scores),strict=True)]
    rows.sort(key=lambda r:(-r["probability_top3"],int(r["horse_no"])))
    return {**base,"pattern":pattern,"runners":rows}


def choose(annual: list[dict]) -> dict:
    """開発2008〜2020年の捕捉非悪化制約付きBrier最小を選ぶ。"""
    summaries={p:mean_metrics([r for r in annual if r["pattern"]==p and "2008"<=r["race_date"][:4]<="2020"]) for p,_ in OPTIONS}
    eligible=[(p,ii) for p,ii in OPTIONS if summaries[p]["top3_captured"]>=summaries["baseline"]["top3_captured"]-1e-12]
    selected=min(eligible,key=lambda x:(summaries[x[0]]["brier"],len(x[1]),x[0]))
    return {"pattern":selected[0],"indices":list(selected[1]),"development":summaries,"eligible":[p for p,_ in eligible]}


def evaluate(sets: list[dict],baseline: list[dict],history: list[dict],facts: list[dict],links: list[dict],general_config: dict) -> dict:
    """4方式72予測を過去以前だけで計算し、選択後の確認期間で切り替えない。"""
    examples=[]
    for target in sets:
        examples.append({**target,"rows":[{**r,**feature(target,r,history,facts,links,[])} for r in target["rows"]]})
    predictions,annual,evidence=[],[],[]
    for i,target in enumerate(examples):
        if i<5:continue
        ev=group_deltas(examples[:i],target,{**general_config,"groups":GROUPS},{"half_life":None,"pooling":"hierarchical","shrinkage":20})
        evidence.append({"race_key":target["race_key"],"rows":ev})
        base=next(p for p in baseline if p["race_key"]==target["race_key"] and p["pattern"]=="N+C+W")
        for pattern,indices in OPTIONS:
            p=combine(base,ev,pattern,indices);predictions.append(p)
            annual.append({k:p[k] for k in ("pattern","race_key","race_date")} | metrics(p,target))
        uniform={**base,"runners":[{**r,"probability_top3":3/len(base["runners"])} for r in base["runners"]]}
        annual.append({"pattern":"uniform","race_key":target["race_key"],"race_date":target["race_date"],**metrics(uniform,target)})
    selection=choose(annual); pattern=selection["pattern"]
    config={"development":[2008,2020],"confirmation":[2021,2025],"bootstrap_seed":240,"bootstrap_repeats":5000}
    comparisons={p:compare(annual,p,"baseline",config) for p,_ in OPTIONS if p!="baseline"}
    usable=pattern!="baseline" and comparisons[pattern]["reference_conditions_met"]
    return {"selection":selection,"comparisons":comparisons,"research_change_eligible":usable,"adopted":False,
            "examples":examples,"predictions":predictions,"annual":annual,"evidence":evidence}
