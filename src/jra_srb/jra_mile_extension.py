"""概要: マイルCSの専用近況と一般評価へ既存H/C/Wを追加比較し、今年の入力へ接続する。
作成日: 2026-11-21
入力: マイルCS23年の監査済み履歴、固定設定、当年カードと国内/海外参照履歴。
出力: 16方式の予測、開発期間選択、海外接続の感度と根拠。
実行例: uv run python scripts/run_jra_mile_extension.py --help
注意事項: 参照済み期間の探索的研究。海外同等能力・校正・利益を保証しない。
"""

from __future__ import annotations

from datetime import date

from .jra_conditions_refinement import group_deltas
from .jra_context_interactions import class_rank, rematch_weight
from .jra_graded_patterns import feature_values
from .jra_head_to_head import features as h2h_features
from .jra_head_to_head import compare
from .jra_race_conditions import probabilities, public_runner, require
from .jra_specific_patterns import make_examples, specific_features, mean_metrics, metrics


def options() -> list[dict]:
    """N/Gの各基準とH/C/W有無の16方式を固定順で返す。"""
    return [{"base": base, "mask": mask, "pattern": base+"".join("+"+g for bit,g in ((1,"H"),(2,"C"),(4,"W")) if mask & bit)}
            for base in ("N", "G") for mask in range(8)]


def extend_examples(target: dict, history: list[dict], config: dict) -> dict:
    """国内履歴から既存定義どおりのH/C/Wを生成し、当該結果を参照しない。"""
    direct = h2h_features(target, target["rows"], history, config)
    rows = {g: [] for g in ("H", "C", "W")}
    for r in target["rows"]:
        h = direct[r["horse_id"]]
        rows["H"].append({**r, **h})
        rows["C"].append({**r, **class_rank(target, r, history)})
        rows["W"].append({**r, **rematch_weight(r, target["rows"], h["meetings"]["h2h_near_distance"], config)})
    return {g: {**target, "rows": values} for g, values in rows.items()}


def combine(target: dict, evidence: dict, option: dict, scale: float) -> dict:
    """指定基準へ固定倍率の追加群だけを加え、合計3の参考確率にする。"""
    additions = {g: {r["horse_id"]: r["deltas"][0] for r in evidence[g]} for g in ("H", "C", "W")}
    scores = []
    for r in evidence[option["base"]]:
        score = r["deltas"][2] if option["base"] == "N" else sum(r["deltas"])/len(r["deltas"])
        score += scale*sum(additions[g][r["horse_id"]] for bit,g in ((1,"H"),(2,"C"),(4,"W")) if option["mask"] & bit)
        scores.append(score)
    rows = [{k:r[k] for k in ("horse_id", "horse_no", "horse_name")} | {"probability_top3": p}
            for r,p in zip(evidence[option["base"]], probabilities(scores), strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return {"race_key":target["race_key"], "race_date":target["race_date"], "venue_code":target["venue_code"],
            "pattern":option["pattern"], "runners":rows}


def choose(annual: list[dict], config: dict) -> dict:
    """開発年のみで捕捉非悪化条件を課し、Brier最小の候補を選ぶ。"""
    lo,hi = config["development"]
    summaries = {o["pattern"]: mean_metrics([r for r in annual if r["pattern"] == o["pattern"] and lo <= int(r["race_date"][:4]) <= hi]) for o in options()}
    require(all(v["races"] == hi-lo+1 for v in summaries.values()), "mile_selection_years")
    eligible = [o for o in options() if summaries[o["pattern"]]["top3_captured"] >= summaries["G"]["top3_captured"]-1e-12]
    selected = min(eligible, key=lambda o:(summaries[o["pattern"]]["brier"],o["mask"].bit_count(),o["base"] != "N",o["pattern"]))
    return {"selected":selected, "development":summaries, "selection_through":hi,
            "eligible":[o["pattern"] for o in eligible], "criterion":"minimum_brier_with_top3_capture_not_below_G"}


def group_evidence(priors: dict, targets: dict, config: dict, general_config: dict, specific_config: dict) -> dict:
    """既存の縮約・同場階層集計を5種類の群へ適用する。"""
    configs = {"G":general_config,"N":{**general_config,"groups":specific_config["series"]["mile"]["groups"]},
               **{g:{**general_config,"groups":config["groups"][g]} for g in ("H","C","W")}}
    return {g:group_deltas(priors[g],targets[g],configs[g],{"half_life":None,"pooling":"hierarchical","shrinkage":20}) for g in configs}


def evaluate(data: dict, config: dict, specific_config: dict, general_config: dict) -> dict:
    """16方式×18年を時系列比較し、既知確認期間で選び直さない。"""
    specific,general,_ = make_examples(data,"mile",specific_config)
    sets = {"N":specific,"G":general, **{g:[] for g in ("H","C","W")}}
    for target in specific:
        extended = extend_examples(target,data["history"],config)
        for g in extended:
            sets[g].append(extended[g])
    predictions,annual,evidence = [],[],[]
    for i,target in enumerate(specific):
        if i < 5:
            continue
        ev = group_evidence({g:v[:i] for g,v in sets.items()},{g:v[i] for g,v in sets.items()},config,general_config,specific_config)
        evidence.append({"race_key":target["race_key"],"groups":ev})
        for o in options():
            p = combine(target,ev,o,config["addition_scale"])
            predictions.append(p)
            annual.append({k:p[k] for k in ("pattern","race_key","race_date")} | metrics(p,target))
        uniform = {"runners":[{**r,"probability_top3":3/len(target["rows"])} for r in target["rows"]]}
        annual.append({"pattern":"uniform","race_key":target["race_key"],"race_date":target["race_date"],**metrics(uniform,target)})
    selection = choose(annual,config)
    selected = selection["selected"]["pattern"]
    renamed = [{**r,"pattern":"general" if r["pattern"] == "G" else r["pattern"]} for r in annual]
    if selected == "G":
        renamed += [{**r,"pattern":"selected_G"} for r in renamed if r["pattern"] == "general"]
    confirmation = compare(renamed,"selected_G" if selected == "G" else selected,"general",config)
    return {"selection":selection,"confirmation":confirmation,"predictions":predictions,"annual":annual,
            "evidence":evidence,"sets":sets,"adopted":False,"status":"exploratory_seen_years"}


def foreign_overlay(race: dict, runner: dict, domestic: list[dict], foreign: list[dict], sp: dict, ge: dict) -> dict:
    """海外の実前走と既知国際格を明示接続し、国内コース値を捏造しない。

    Args:
        race: 予想日と距離。
        runner: 同定済み今回馬。
        domestic: 同一馬の国内履歴。
        foreign: 原資料と恒久IDを保持した非JRA履歴。
        sp: 国内だけで作った専用特徴。呼出し側のコピーを更新する。
        ge: 国内だけで作った一般特徴。呼出し側のコピーを更新する。
    Returns:
        海外由来変更と参照レコード。非JRAを国内対戦Hへ流さない。
    """
    prior = [r for r in foreign if r["horse_id"] == runner["horse_id"] and r["race_date"] < race["race_date"]]
    local = [r for r in domestic if r["horse_id"] == runner["horse_id"] and r["race_date"] < race["race_date"] and r["status"] == "active"]
    if not prior:
        return {"used":False}
    require(len({r["race_date"] for r in prior}) == len(prior),"mile_nonjra_date_conflict")
    last = max(prior,key=lambda r:r["race_date"])
    latest_local = max((r["race_date"] for r in local),default="")
    changed = {}
    if last["race_date"] > latest_local:
        rank,gap,dist = last["rank"],(date.fromisoformat(race["race_date"])-date.fromisoformat(last["race_date"])).days,last["distance"]
        grade = {"GI":"A","GII":"B","GIII":"C"}.get(last.get("international_grade_raw"))
        sp["values"].update(last_rank=("1着" if rank == 1 else "2〜3着" if rank <= 3 else "4〜5着" if rank <= 5 else "6着以下") if rank else None,
            layoff="1〜28日" if gap <= 28 else "29〜56日" if gap <= 56 else "57〜112日" if gap <= 112 else "113日以上",
            prep_route="その他",prep_grade=grade,
            prep_distance=("1200以下" if dist <= 1200 else str(dist) if dist in (1400,1600,1800) else "2000以上" if dist >= 2000 else "その他") if last["surface_raw"] == "芝" else "ダート")
        ge["values"].update(previous_race=last["race_name_raw"],previous_grade=grade,previous_weight_rule=None,previous_symbol=None,
            previous_rank=("1〜3着" if rank <= 3 else "4〜5着" if rank <= 5 else "6着以下") if rank else None,
            interval="28日以下" if gap <= 28 else "29〜56日" if gap <= 56 else "57日以上",
            previous_distance="1800m以下" if dist <= 1800 else "1801〜2000m" if dist <= 2000 else "2001〜2200m" if dist <= 2200 else "2201m以上",
            distance_change="延長" if race["distance"] > dist else "短縮" if race["distance"] < dist else "同距離")
        pw = last.get("weight_carried")
        delta = runner["weight_carried"]-pw if pw is not None else None
        ge["values"]["weight_change"] = None if delta is None else "増" if delta > .01 else "減" if delta < -.01 else "同"
        sp.update(latest_date=last["race_date"],previous={"jra_race_key":None,"source_record_id":f"nonJRA:{runner['horse_id']}:{last['race_date']}",**last})
        changed = {"actual_previous":last,"interval_days":gap,"domestic_previous_date":latest_local or None}
    good = [r for r in prior if r.get("rank") and r["rank"] <= 3 and r["surface_raw"] == "芝" and r["distance"] == 1600]
    graded = [r for r in good if r.get("international_grade_raw") in ("GI","GII","GIII")]
    g1 = [r for r in graded if r["international_grade_raw"] == "GI"]
    if graded:
        sp["values"]["mile_graded"] = "確認あり"
        ge["values"]["graded_top3"] = "確認あり"
    if g1:
        current = sp["values"].get("mile_g1")
        sp["values"]["mile_g1"] = "勝利" if current == "勝利" or any(r["rank"] == 1 for r in g1) else "2〜3着のみ"
    if not local:
        sp["values"]["same_stage"] = None
        ge["values"].update(course_distance_top3=None,repeat_top3=None)
    return {"used":True,"previous_change":changed,"international_mile_graded_records":graded,
            "warning":"歴年の海外網羅なし・日本への同等能力換算なし"}


def live_targets(card: dict, history: list[dict], foreign: list[dict], config: dict, connect_foreign: bool) -> tuple[dict,dict]:
    """全有効馬の国内特徴を作り、海外実前走を任意で接続する。"""
    target = {k:v for k,v in card.items() if k != "runners"}
    groups = {"N":[],"G":[]}
    notes = {}
    for r in card["runners"]:
        if r["status"] != "active":
            continue
        sp = {**public_runner(r),**specific_features("mile",card,r,history)}
        ge = {**public_runner(r),"values":feature_values(card,r,history)}
        notes[r["horse_id"]] = foreign_overlay(card,r,history,foreign,sp,ge) if connect_foreign else {"used":False}
        groups["N"].append(sp); groups["G"].append(ge)
    targets = {g:{**target,"rows":rows} for g,rows in groups.items()}
    targets.update(extend_examples(targets["N"],history,config))
    # 実前走が海外の場合、国内直近をCの前走として代用しない。
    if connect_foreign:
        for r in targets["C"]["rows"]:
            note = notes[r["horse_id"]]
            if note.get("previous_change"):
                last = note["previous_change"]["actual_previous"]
                grade = {"GI":"A","GII":"B","GIII":"C"}.get(last.get("international_grade_raw"))
                rank = last.get("rank")
                bucket = "1着" if rank == 1 else "2〜3着" if rank and rank <= 3 else "4〜5着" if rank and rank <= 5 else "6着以下"
                r["values"] = {"class_rank":grade+"|"+bucket if grade and rank else None}
                r["previous_evidence"] = {"jra_race_key":None,**last}
    return targets,notes


def forecast(result: dict, card: dict, history: list[dict], foreign: list[dict], config: dict, specific_config: dict, general_config: dict) -> dict:
    """選択済み方式を全過去年で固定集計し、国内限定との差を保存する。"""
    require(card["race_date"] == "2026-11-22" and card["venue_code"] == "08" and card["distance"] == 1600,"mile_live_scope")
    selected = result["selection"]["selected"]
    outputs = {}
    for connect in (False,True):
        targets,notes = live_targets(card,history,foreign,config,connect)
        ev = group_evidence(result["sets"],targets,config,general_config,specific_config)
        outputs["international_connected" if connect else "domestic_only"] = {"forecast":combine(targets["N"],ev,selected,config["addition_scale"]),
            "all_patterns":[combine(targets["N"],ev,o,config["addition_scale"]) for o in options()],"evidence":ev,"targets":targets,"foreign_notes":notes}
    return outputs
