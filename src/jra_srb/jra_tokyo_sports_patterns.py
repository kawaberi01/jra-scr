"""概要: 東スポ杯2歳S固有の経路・キャリア・近況・適性を固定候補で検証する。
作成日: 2026-11-22
入力: 監査済み23開催・各対象日前履歴・当年カード。
出力: 28条件の根拠、34方式の時系列比較、固定選択と当年予想。
実行例: uv run python scripts/run_tokyo_sports_patterns.py --help
注意事項: 過去年は事後属性。一部期間は公式傾向を参照済み。確率未校正。
"""

from __future__ import annotations

from datetime import date
from itertools import combinations
import math

from .jra_conditions_refinement import candidate_prediction, group_deltas
from .jra_graded_patterns import feature_values, surface
from .jra_race_conditions import probabilities, public_runner, require
from .jra_specific_patterns import metrics, mean_metrics

GROUPS = {"R 前走経路":["prep_class","prep_distance","prep_route"],
          "C キャリア":["career","unbeaten_top3","debut_win"],
          "I 近況":["last_rank","layoff"],
          "S 舞台適性":["tokyo_top3","turf1800_top3","distance_change"]}
ATOM_LABELS = {"prev_win":"前走1着","prev_top3":"前走3着以内","prev1800":"前走芝1800m",
    "career_le3":"キャリア3戦以内","career1":"キャリア1戦","never_below3":"全出走3着以内",
    "tokyo1800_top3":"東京芝1800m3着内実績","all_wins":"全勝","gap28_84":"間隔28〜84日",
    "graded_top3":"重賞3着内実績","debut_win":"新馬勝ち","prev_debut":"前走新馬",
    "prev_open_top3":"前走OP以上3着以内","tokyo_experience":"東京経験"}
MAIN = ("prev_win","prev1800","career_le3","never_below3")
PAIR_KEYS = [("prev_win","prev1800"),("prev_win","career_le3"),("career_le3","never_below3"),
    ("career1","prev1800"),("prev_win","tokyo_experience"),("prev1800","never_below3"),
    ("prev_open_top3","career_le3"),("gap28_84","prev_win")]
TRIPLE_KEYS = [("prev_win","prev1800","career_le3"),("prev_win","career_le3","never_below3"),
    ("prev1800","career_le3","never_below3"),("prev_win","prev1800","never_below3")]


def tri_and(values: list[bool | None]) -> bool | None:
    """不明を非該当とせず三値ANDを返す。"""
    return False if False in values else None if None in values else True


def tri_or(values: list[bool | None]) -> bool | None:
    """不明を非該当とせず三値ORを返す。"""
    return True if True in values else None if None in values else False


def race_class(row: dict) -> str | None:
    """RA検証済みの格と競走名から新馬・未勝利・条件・OP・重賞を区別する。"""
    if not row.get("conditions_verified",row.get("ra_verified",False)):
        return None
    name = row.get("race_name","")
    if "未勝利" in name or row.get("condition_code") == "703":
        return "未勝利"
    if "新馬" in name or "メイクデビュー" in name or row.get("condition_code") == "701":
        return "新馬"
    if row.get("grade") in ("A","B","C"):
        return "重賞"
    if row.get("condition_code") == "999" or row.get("grade") == "L":
        return "OP"
    return "条件戦"


def features(race: dict, runner: dict, history: list[dict]) -> dict:
    """当該日前だけで特徴・原子条件と参照走を作る。

    Notes:
        キャリア全体を使う条件は、最初の収録走が新馬と確認できる場合だけ判定する。
        取消・除外を除き、中止等は全走好走の肯定材料にしない。
    """
    prior = sorted([r for r in history if r["horse_id"] == runner["horse_id"] and r["race_date"] < race["race_date"] and r["status"] == "active"],key=lambda r:(r["race_date"],r["race_key"]))
    require(len({r["race_date"] for r in prior}) == len(prior),"tospo_history_date_duplicate")
    vals = {k:None for cols in GROUPS.values() for k in cols}
    atoms = dict.fromkeys(ATOM_LABELS)
    if not prior:
        return {"values":vals,"atoms":atoms,"history":[],"career_complete":False}
    last=prior[-1]; rank=last.get("rank"); gap=(date.fromisoformat(race["race_date"])-date.fromisoformat(last["race_date"])).days
    complete=race_class(prior[0]) == "新馬"
    ranks_known=all(r.get("rank") is not None for r in prior)
    alltop=all(r["rank"] <= 3 for r in prior) if ranks_known and complete else None
    good=[r for r in prior if r.get("rank") and r["rank"] <= 3]
    route=next((s for s in ("札幌2歳","新潟2歳","萩","アイビー","芙蓉") if s in last["race_name"].replace("２","2")),"その他")
    vals.update(prep_class=race_class(last),prep_distance=(str(last["distance"]) if surface(last["track_code"]) == "turf" else "非芝"),
        prep_route=route,career=(str(len(prior)) if len(prior)<=3 else "4以上") if complete else None,
        unbeaten_top3=str(alltop) if alltop is not None else None,
        debut_win=str(prior[0]["rank"] == 1) if complete and prior[0].get("rank") else None,
        last_rank="1着" if rank == 1 else "2〜3着" if rank and rank<=3 else "4着以下" if rank else None,
        layoff="27日以下" if gap<28 else "28〜56日" if gap<=56 else "57〜84日" if gap<=84 else "85日以上",
        tokyo_top3=str(any(r["venue_code"] == "05" and surface(r["track_code"]) == "turf" for r in good)),
        turf1800_top3=str(any(r["distance"] == 1800 and surface(r["track_code"]) == "turf" for r in good)),
        distance_change="延長" if last["distance"]<1800 else "短縮" if last["distance"]>1800 else "同距離")
    atoms.update(prev_win=rank==1 if rank else None,prev_top3=rank<=3 if rank else None,
        prev1800=last["distance"]==1800 and surface(last["track_code"])=="turf",career_le3=len(prior)<=3 if complete else None,
        career1=len(prior)==1 if complete else None,never_below3=alltop,
        tokyo1800_top3=any(r["venue_code"]=="05" and r["distance"]==1800 and surface(r["track_code"])=="turf" for r in good),
        all_wins=all(r["rank"]==1 for r in prior) if complete and ranks_known else None,gap28_84=28<=gap<=84,
        graded_top3=any(r.get("grade") in ("A","B","C") for r in good),
        debut_win=prior[0]["rank"]==1 if complete and prior[0].get("rank") else None,
        prev_debut=race_class(last)=="新馬" if race_class(last) else None,
        prev_open_top3=rank<=3 and race_class(last) in ("OP","重賞") if rank and race_class(last) else None,
        tokyo_experience=any(r["venue_code"]=="05" for r in prior))
    return {"values":vals,"atoms":atoms,"history":prior,"career_complete":complete,"gap_days":gap,
            "previous":last,"career_count_observed":len(prior)}


def rule_catalogue() -> list[dict]:
    """単独14・二条件8・三条件4・救済OR2を固定順で返す。"""
    result=[{"id":k,"label":v,"op":"atom","keys":[k]} for k,v in ATOM_LABELS.items()]
    for keys in [*PAIR_KEYS,*TRIPLE_KEYS]:
        result.append({"id":"&".join(keys),"label":" ＋ ".join(ATOM_LABELS[k] for k in keys),"op":"and","keys":list(keys)})
    for keys in [("prev_win","prev_open_top3"),("career_le3","graded_top3")]:
        result.append({"id":"|".join(keys),"label":" または ".join(ATOM_LABELS[k] for k in keys),"op":"or","keys":list(keys)})
    require(len(result)==28,"tospo_28_rules")
    return result


def rule_value(atoms: dict, rule: dict) -> bool | None:
    """定義済み条件を三値で評価する。"""
    values=[atoms[k] for k in rule["keys"]]
    return tri_or(values) if rule["op"]=="or" else tri_and(values)


def examples(data: dict) -> dict:
    """結果をoutcomeへ隔離し、専用・一般・四条件型の特徴集合を作る。"""
    sets={"specific":[],"general":[],"joint":[]}
    for race in sorted(data["races"],key=lambda r:r["race_date"]):
        base={k:v for k,v in race.items() if k!="runners"};base["evaluation_eligible"]=True
        rows={k:[] for k in sets}
        for r in race["runners"]:
            f=features(race,r,data["history"])
            common={**public_runner(r),"outcome":{"top3":bool(r.get("rank") and r["rank"]<=3)},"finish_rank":r.get("rank")}
            rows["specific"].append({**common,**f})
            rows["general"].append({**common,"values":feature_values(race,r,data["history"])})
            joint=None if any(f["atoms"][k] is None for k in MAIN) else "".join(str(int(f["atoms"][k])) for k in MAIN)
            rows["joint"].append({**common,"values":{"joint4":joint}})
        for k in sets:sets[k].append({**base,"rows":rows[k]})
    return sets


def options() -> list[dict]:
    """固定32候補を返す。"""
    return [{"pattern":f"S{m:02d}"+("+G" if blend else ""),"mask":m,"blend":blend,
             "weights":[int(bool(m&(1<<i))) for i in range(4)],"scale":1,"family":"specific"} for m in range(1,16) for blend in (False,True)] + [
             {"pattern":"rule4_equal","mask":0,"blend":False},{"pattern":"rule4_joint","mask":0,"blend":False}]


def forecasts(sets: dict, target_sets: dict, general_config: dict) -> tuple[list[dict],dict]:
    """同名過去年のみの縮約で全固定候補を計算する。"""
    params={"half_life":None,"pooling":"hierarchical","shrinkage":20}
    cfg={**general_config,"groups":GROUPS}
    ev=group_deltas(sets["specific"],target_sets["specific"],cfg,params)
    ge=group_deltas(sets["general"],target_sets["general"],general_config,params)
    je=group_deltas(sets["joint"],target_sets["joint"],{**general_config,"groups":{"主要4同時型":["joint4"]}},params)
    gp=candidate_prediction(ge,target_sets["general"],{"pattern":"general","family":"baseline","weights":[1]*5,"scale":1})
    out=[gp];gprob={r["horse_no"]:r["probability_top3"] for r in gp["runners"]}
    for o in options():
        if o["pattern"]=="rule4_joint":
            p=candidate_prediction(je,target_sets["specific"],{"pattern":o["pattern"],"family":"rule","weights":[1],"scale":1})
        elif o["pattern"]=="rule4_equal":
            scores=[sum(float(r["atoms"][k]) if r["atoms"][k] is not None else .5 for k in MAIN)/4 for r in target_sets["specific"]["rows"]]
            rows=[{k:r[k] for k in ("horse_id","horse_no","horse_name")} | {"probability_top3":p} for r,p in zip(target_sets["specific"]["rows"],probabilities(scores),strict=True)]
            p={"race_key":target_sets["specific"]["race_key"],"pattern":o["pattern"],"runners":rows}
        else:
            p=candidate_prediction(ev,target_sets["specific"],o)
            if o["blend"]:
                for r in p["runners"]:r["probability_top3"]=(2*r["probability_top3"]+gprob[r["horse_no"]])/3
        p["runners"].sort(key=lambda r:(-r["probability_top3"],int(r["horse_no"])))
        out.append(p)
    out.append({**gp,"pattern":"uniform","runners":[{**r,"probability_top3":3/len(gp["runners"])} for r in gp["runners"]]})
    require(len(out)==34 and all(abs(sum(r["probability_top3"] for r in p["runners"])-3)<1e-9 for p in out),"tospo_34_probability_contract")
    return out,{"specific":ev,"general":ge,"joint":je}


def evaluate(data: dict, general_config: dict) -> dict:
    """開発で一度選択し、中間年で採否固定後、後続年を再選択せず監査する。"""
    sets=examples(data);annual=[];preds=[]
    for i,target in enumerate(sets["specific"]):
        if i<5:continue
        forecasts_,_=forecasts({k:v[:i] for k,v in sets.items()},{k:v[i] for k,v in sets.items()},general_config)
        for p in forecasts_:
            annual.append({"pattern":p["pattern"],"race_date":target["race_date"],"race_key":target["race_key"],**metrics(p,target)})
            preds.append(p)
    periods={"development":[2008,2015],"validation":[2016,2020],"audit":[2021,2025]}
    summaries={period:{pattern:mean_metrics([r for r in annual if r["pattern"]==pattern and lo<=int(r["race_date"][:4])<=hi]) for pattern in [o["pattern"] for o in options()]+["general","uniform"]} for period,(lo,hi) in periods.items()}
    dev=summaries["development"];eligible=[o for o in options() if dev[o["pattern"]]["top3_captured"]>=dev["general"]["top3_captured"]-1e-12]
    selected=min(eligible,key=lambda o:(dev[o["pattern"]]["brier"],o["mask"].bit_count(),o["blend"],o["pattern"]))["pattern"] if eligible else "S15"
    a,b=summaries["validation"][selected],summaries["validation"]["general"]
    improved=sum(next(r["brier"] for r in annual if r["pattern"]==selected and int(r["race_date"][:4])==y)<next(r["brier"] for r in annual if r["pattern"]=="general" and int(r["race_date"][:4])==y) for y in range(2016,2021))
    checks={"brier_1pct":a["brier"]<=.99*b["brier"],"capture_not_worse":a["top3_captured"]>=b["top3_captured"]-1e-12,"logloss_not_worse":a["logloss"]<=b["logloss"],"majority_years":improved>=3}
    used=selected if all(checks.values()) else "general"
    require(len(preds)==612,"tospo_612_predictions")
    return {"selection":{"candidate":selected,"used_pattern":used,"validation_checks":checks,"validation_improved_years":improved,"selected_through":2015,"adoption_through":2020,"audit_used_for_selection":False},
        "summaries":summaries,"annual":annual,"predictions":preds,"sets":sets,"periods":periods}


def records(sets: dict) -> list[dict]:
    """28条件について該当/非該当/不明の四区分成績と全明細を保存する。"""
    out=[]
    for rule in rule_catalogue():
        members=[{"race_date":race["race_date"],"race_key":race["race_key"],"horse_no":r["horse_no"],"horse_id":r["horse_id"],"horse_name":r["horse_name"],
                  "rank":r["finish_rank"],"match":rule_value(r["atoms"],rule),"history_keys":[h["race_key"] for h in r["history"]]} for race in sets["specific"] for r in race["rows"]]
        periods={"all":[2003,2025],"development":[2008,2015],"validation":[2016,2020],"audit":[2021,2025],"recent10":[2016,2025]}
        stats={}
        for name,(lo,hi) in periods.items():
            rows=[r for r in members if lo<=int(r["race_date"][:4])<=hi]
            stats[name]={}
            for match,label in [(True,"matched"),(False,"unmatched"),(None,"unknown")]:
                selected=[r for r in rows if r["match"] is match]
                counts=[sum(r["rank"]==k for r in selected) for k in (1,2,3)];counts.append(len(selected)-sum(counts))
                stats[name][label]={"record":counts,"n":len(selected),"top3_rate":sum(counts[:3])/len(selected) if selected else None}
        out.append({**rule,"periods":stats,"members":members})
    return out
