"""概要: マイルCSの前哨戦・同年経路・前年実績・消去48条件を事実ベースで比較する。
作成日: 2026-11-22
入力: 同定済み競走・出走馬・対象日前の保存履歴。
出力: 三値の経路判定、根拠、該当/収録内なし/不明の成績と消去候補評価。
実行例: uv run python scripts/run_jra_route_patterns.py --help
注意事項: 国内履歴の欠落を否定事実にしない。予想確率・購入・DB書込みは行わない。
"""

from __future__ import annotations

from collections import defaultdict
from .jra_specific_patterns import route_name
from .jra_race_conditions import require

ROUTES = ("富士S","スワンS","毎日王冠","天皇賞秋","スプリンターズS","安田記念")


def patterns() -> list[dict]:
    """仕様050の48条件を固定順で返す。"""
    rows = []
    for scope,label in (("previous","直前収録走"),("same_year","同年出走")):
        for i,route in enumerate(ROUTES,1):
            for limit,result in ((None,"出走"),(1,"勝利"),(3,"3着以内")):
                rows.append({"id":f"{scope}-{i}-{limit or 0}","kind":scope,"route":route,"rank_limit":limit,"label":f"{label}：{route}・{result}"})
    for i,(first,last) in enumerate((("安田記念","富士S"),("毎日王冠","天皇賞秋")),1):
        for limit,result in ((None,"出走"),(3,"3着以内")):
            rows.append({"id":f"sequence-{i}-{limit or 0}","kind":"sequence","first":first,"route":last,"rank_limit":limit,"label":f"同年{first}→{last}・後段{result}"})
    for limit,result in ((None,"出走"),(3,"3着以内")):
        rows.append({"id":f"previous_year-{limit or 0}","kind":"previous_year","rank_limit":limit,"label":f"前年マイルCS・{result}"})
    for limit in (1,3,5):
        rows.append({"id":f"previous_result-{limit}","kind":"previous_result","rank_limit":limit,"label":f"前走{limit}着以内"})
    for age in (4,5,6):
        rows.append({"id":f"age_max-{age}","kind":"age_max","age_max":age,"rank_limit":None,"label":f"{age}歳以下（{age+1}歳以上を除外）"})
    require(len(rows)==48,"route_pattern_count")
    return rows


def match(race: dict,runner: dict,history: list[dict],pattern: dict) -> dict:
    """対象日前の出走経路を三値判定し、採用した過去走だけを根拠に残す。"""
    if pattern["kind"]=="age_max":
        age=runner.get("age")
        known=type(age) is int and 2<=age<=15
        return {"matched":age<=pattern["age_max"] if known else None,"reason":"current_age" if known else "age_unknown",
                "evidence":[{"current_age":age,"age_max":pattern["age_max"]}]}
    prior = sorted([h for h in history if h["horse_id"]==runner["horse_id"] and h["race_date"]<race["race_date"] and h["status"]=="active"],key=lambda h:(h["race_date"],h["race_key"]))
    require(len({h["race_date"] for h in prior})==len(prior),"route_same_day_conflict")
    if not prior:
        return {"matched":None,"reason":"no_prior_records","evidence":[]}
    kind = pattern["kind"]
    same = [h for h in prior if h["race_date"][:4]==race["race_date"][:4]]
    if kind=="previous_result":
        candidates=[prior[-1]]
    elif kind=="previous":
        candidates = [prior[-1]] if route_name(prior[-1]["race_name"])==pattern["route"] else []
    elif kind=="same_year":
        candidates = [h for h in same if route_name(h["race_name"])==pattern["route"]]
    elif kind=="sequence":
        candidates = [h for h in same if route_name(h["race_name"])==pattern["route"] and any(
            a["race_date"]<h["race_date"] and route_name(a["race_name"])==pattern["first"] for a in same)]
    else:
        require(kind=="previous_year","route_kind")
        candidates = [h for h in prior if int(h["race_date"][:4])==int(race["race_date"][:4])-1 and h["race_name"]=="マイルチャンピオンシップ"]
    limit = pattern["rank_limit"]
    selected = candidates if limit is None else [h for h in candidates if type(h.get("rank")) is int and 1<=h["rank"]<=limit]
    unknown = limit is not None and any(not h.get("rank") for h in candidates)
    value = True if selected else None if unknown else False
    return {"matched":value,"reason":"matched" if value is True else "rank_unknown" if value is None else "not_found_in_stored_history",
            "evidence":[{k:h.get(k) for k in ("race_key","race_date","race_name","rank","distance","source_kind")} for h in selected],
            "latest_stored_date":prior[-1]["race_date"]}


def examples(data: dict) -> list[dict]:
    """監査済み全開催の事前経路判定と当該結果を分離して保持する。"""
    history = defaultdict(list)
    for h in data["history"]:
        history[h["horse_id"]].append(h)
    rows = []
    for runner in data["target_rows"]:
        if runner["status"]!="active":
            continue
        rows.append({k:runner.get(k) for k in ("race_key","race_date","horse_no","horse_id","horse_name","age","rank")} |
            {"patterns":{p["id"]:match(runner,runner,history[runner["horse_id"]],p) for p in patterns()}})
    return sorted(rows,key=lambda r:(r["race_date"],int(r["horse_no"])))


def counts(rows: list[dict]) -> dict:
    """出走・勝利・3着内の実数と率を返し、空の率はNoneとする。"""
    n = len(rows); wins = sum(r.get("rank")==1 for r in rows)
    top3 = sum(type(r.get("rank")) is int and 1<=r["rank"]<=3 for r in rows)
    return {"runners":n,"wins":wins,"top3":top3,"win_rate":wins/n if n else None,"top3_rate":top3/n if n else None}


def summarize(rows: list[dict],pattern_id: str) -> dict:
    """該当/収録内なし/不明を別集計し、不明を残した場合の保持率を返す。"""
    buckets = {"matched":[r for r in rows if r["patterns"][pattern_id]["matched"] is True],
               "not_found":[r for r in rows if r["patterns"][pattern_id]["matched"] is False],
               "unknown":[r for r in rows if r["patterns"][pattern_id]["matched"] is None]}
    totals = counts(rows); retained = buckets["matched"]+buckets["unknown"]
    per_race = defaultdict(list)
    for r in rows:
        per_race[r["race_key"]].append(r)
    return {**{k:counts(v) for k,v in buckets.items()},"total":totals,"retained":counts(retained),
            "matched_editions":len({r["race_key"] for r in buckets["matched"]}),
            "retained_winner_rate":counts(retained)["wins"]/totals["wins"] if totals["wins"] else None,
            "retained_top3_rate":counts(retained)["top3"]/totals["top3"] if totals["top3"] else None,
            "mean_retained_fraction":sum(sum(r["patterns"][pattern_id]["matched"] is not False for r in rr)/len(rr) for rr in per_race.values())/len(per_race) if per_race else None,
            "excluded_winners":[{k:r[k] for k in ("race_date","horse_no","horse_name")} for r in buckets["not_found"] if r.get("rank")==1]}


def evaluate(rows: list[dict]) -> dict:
    """開発期間だけで消去条件を選び、参照確認期間で再選択しない。"""
    periods = {"all":rows,"development":[r for r in rows if "2008"<=r["race_date"][:4]<="2020"],
               "confirmation":[r for r in rows if "2021"<=r["race_date"][:4]<="2025"]}
    results = [{**p,"periods":{k:summarize(v,p["id"]) for k,v in periods.items()}} for p in patterns()]
    eligible = [p for p in results if p["periods"]["development"]["retained_winner_rate"]==1 and
                p["periods"]["development"]["matched"]["runners"]>=20 and p["periods"]["development"]["matched_editions"]>=5 and
                p["periods"]["development"]["mean_retained_fraction"]<=.7]
    selected = min(eligible,key=lambda p:(p["periods"]["development"]["mean_retained_fraction"],p["id"])) if eligible else None
    return {"patterns":results,"selected_elimination_pattern":selected,"adopted":False,
            "status":"exploratory_stored_JRA_history_not_proven_complete","selection_period":[2008,2020],"confirmation_period":[2021,2025]}


def live(card: dict,domestic: list[dict],foreign: list[dict]) -> list[dict]:
    """保存今年カードへ実海外前走を接続し、全48条件の該当根拠を返す。"""
    history = list(domestic)
    for h in foreign:
        require(h["jra_race_key"] is None,"route_nonjra_identity")
        history.append({"horse_id":h["horse_id"],"race_key":f"nonJRA:{h['horse_id']}:{h['race_date']}",
            "race_date":h["race_date"],"race_name":h["race_name_raw"],"rank":h["rank"],"distance":h["distance"],
            "status":"active","source_kind":"official_nonJRA_reference"})
    return [{**r,"patterns":{p["id"]:match(card,r,history,p) for p in patterns()}} for r in card["runners"] if r["status"]=="active"]
