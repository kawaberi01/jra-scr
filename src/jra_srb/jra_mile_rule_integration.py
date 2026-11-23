"""概要: マイルCSの原子条件・複合条件・救済を旧予測へ追加比較する。
作成日: 2026-11-22
入力: 固定の旧予測、同名競走と馬の過去走、今年の確認済み出馬表。
出力: 条件判定と根拠、1-2-3-着外、51方式の時系列成績と採否。
実行例: uv run python scripts/run_jra_mile_rule_integration.py --help
注意事項: 探索的研究。過去海外履歴の欠落があり、強制消去や実購入はしない。
"""

from itertools import combinations
import math

from .jra_conditions_refinement import group_deltas
from .jra_head_to_head import compare
from .jra_race_conditions import probabilities, require
from .jra_specific_patterns import mean_metrics, metrics, route_name

ATOMS = {
    "age34": "3歳または4歳",
    "previous5": "前走5着以内",
    "route4": "前走が富士S・毎日王冠・天皇賞秋・スプリンターズS",
    "mile_g1_top2": "収録内に芝1600m国際GI2着以内あり",
    "kyoto1600_top3": "収録内に京都芝1600m3着以内あり",
    "under6": "6歳未満",
}
UNAVAILABLE = [
    {"id": "breeder_rescue", "condition": "前走1着 AND 前走GII AND 社台系生産馬", "reason": "生産者分類とID対応の充足未監査。非該当へ置換しない"},
    {"id": "kansai_rescue", "condition": "前走富士S/毎日王冠 AND その走5番人気以内 AND 関西馬", "reason": "歴年前走人気と所属の統一入力が未接続"},
    {"id": "named_jockey", "condition": "資料指定の日本人騎手", "reason": "指定リストが提供資料にない"},
    {"id": "sustained_finish", "condition": "下り坂からの個馬の末脚持続力", "reason": "定義・個馬区間計測が未整備。上がり順位と同一視しない"},
]


def expression(tree: dict, values: dict):
    """真・偽・不明の三値でAND/OR/NOTを評価し、欠測を偽にしない。"""
    if "atom" in tree:
        return values[tree["atom"]]
    op, children = tree["op"], tree["children"]
    require(op in ("and", "or", "not") and bool(children), "rule_operator")
    args = [expression(c, values) for c in children]
    if op == "not":
        require(len(args) == 1, "rule_not_arity")
        return None if args[0] is None else not args[0]
    if op == "and":
        return False if False in args else None if None in args else True
    return True if True in args else None if None in args else False


def atom(key: str) -> dict:
    """条件式用の原子参照を作る。"""
    return {"atom": key}


def rules() -> list[dict]:
    """事前仕様の単独6・二条件15・三条件2・救済2を固定列挙する。"""
    result = [{"id": k, "label": label, "tree": atom(k), "role": "好走候補", "complexity": 1} for k, label in ATOMS.items()]
    for a, b in combinations(ATOMS, 2):
        result.append({"id": a+"__"+b, "label": ATOMS[a]+" ＋ "+ATOMS[b],
                       "tree": {"op": "and", "children": [atom(a), atom(b)]}, "role": "複合好走候補", "complexity": 2})
    for keys in (("age34", "previous5", "route4"), ("mile_g1_top2", "previous5", "route4")):
        result.append({"id": "__".join(keys), "label": " ＋ ".join(ATOMS[k] for k in keys),
                       "tree": {"op": "and", "children": [atom(k) for k in keys]}, "role": "複合好走候補", "complexity": 3})
    for key, first, second, label in (
        ("rescue_previous", "previous5", "mile_g1_top2", "前走5着以内、またはマイルGI連対実績で救済"),
        ("rescue_age", "under6", "fuji_top2", "6歳未満、または前走富士S2着以内で救済"),
    ):
        result.append({"id": key, "label": label, "role": "消去仮説の救済候補", "complexity": 2,
                       "tree": {"op": "or", "children": [atom(first), atom(second)]},
                       "parent_condition": first, "rescue_condition": second})
    require(len(result) == 25, "rule_candidate_count")
    return result


def turf(row: dict) -> bool:
    """保存済みJRAコードまたは明示海外表記で芝を確認する。"""
    return row.get("surface_raw") == "芝" or str(row.get("track_code", "")).isdigit() and 10 <= int(row["track_code"]) <= 22


def features(race: dict, runner: dict, history: list[dict], foreign: list[dict]) -> dict:
    """対象日前だけの実績と直前走を取得し、全条件の値と参照走を残す。

    Args:
        race: 対象競走の日付と同定情報。
        runner: 恒久馬IDと現在年齢を持つ出走馬。
        history: 保存済み国内履歴。全世界の完全履歴とはみなさない。
        foreign: 今年の公式馬別資料から確認した非JRA走。
    Returns:
        原子条件、参照走、25複合判定、救済判定。
    """
    prior = [h for h in history if h["horse_id"] == runner["horse_id"] and h["race_date"] < race["race_date"] and h.get("status") == "active"]
    prior += [{**h, "race_key": "nonJRA:"+h["horse_id"]+":"+h["race_date"], "foreign": True} for h in foreign
              if h["horse_id"] == runner["horse_id"] and h["race_date"] < race["race_date"] and h.get("rank")]
    prior.sort(key=lambda h: (h["race_date"], h["race_key"]))
    previous = prior[-1] if prior else None
    age = runner.get("age")
    valid_age = type(age) is int and 2 <= age <= 15
    rank = previous.get("rank") if previous else None
    has_rank = type(rank) is int and rank > 0
    name = (previous.get("race_name") or previous.get("race_name_raw") or "") if previous else ""
    route = route_name(name) if name else None
    g1 = [h for h in prior if turf(h) and h.get("distance") == 1600 and (h.get("grade") == "A" or h.get("international_grade_raw") == "GI")
          and type(h.get("rank")) is int and 0 < h["rank"] <= 2]
    stage = [h for h in prior if turf(h) and h.get("distance") == 1600 and h.get("venue_code") == "08"
             and type(h.get("rank")) is int and 0 < h["rank"] <= 3]
    values = {
        "age34": age in (3, 4) if valid_age else None,
        "previous5": rank <= 5 if has_rank else None,
        "route4": route in ("富士S", "毎日王冠", "天皇賞秋", "スプリンターズS") if route is not None else None,
        "mile_g1_top2": bool(g1) if prior else None,
        "kyoto1600_top3": bool(stage) if prior else None,
        "under6": age < 6 if valid_age else None,
        "fuji_top2": route == "富士S" and rank <= 2 if has_rank and route is not None else None,
    }
    refs = {"age": age, "previous": previous, "mile_g1_top2": g1, "kyoto1600_top3": stage,
            "history_count": len(prior), "history_latest_date": previous["race_date"] if previous else None,
            "coverage": "保存国内履歴＋今年の明示非JRA資料。未確認は全世界の実績なしを意味しない"}
    matched = {r["id"]: expression(r["tree"], values) for r in rules()}
    rescue = {}
    for r in rules():
        if "parent_condition" not in r:
            continue
        parent, saved = values[r["parent_condition"]], values[r["rescue_condition"]]
        rescue[r["id"]] = {"parent_keep": parent, "rescue": saved,
            "status": "通常残す" if parent is True else "親条件不明" if parent is None else "救済" if saved is True else "救済不明" if saved is None else "割引候補"}
    return {"atoms": values, "matches": matched, "references": refs, "rescue": rescue,
            "values": {k: "該当" if v is True else "非該当（実績は収録内確認なし）" if v is False else None for k, v in matched.items()}}


def counts(rows: list[dict]) -> dict:
    """実出走行を1着・2着・3着・着外へ集計し、未確定行は拒否する。"""
    result = {"runners": len(rows), "first": 0, "second": 0, "third": 0, "other": 0}
    for row in rows:
        rank = row.get("finish_rank")
        require(type(rank) is int and rank > 0 or row.get("nonfinish_confirmed") is True, "rule_result_unconfirmed")
        result[{1: "first", 2: "second", 3: "third"}.get(rank, "other")] += 1
    require(sum(result[k] for k in ("first", "second", "third", "other")) == result["runners"], "rule_count_sum")
    result["record"] = "-".join(str(result[k]) for k in ("first", "second", "third", "other"))
    result["top3_rate"] = (result["first"]+result["second"]+result["third"])/len(rows) if rows else None
    return result


def summaries(sets: list[dict]) -> list[dict]:
    """全条件の三群成績・年度/場別成績・救済内訳を根拠明細へ接続する。"""
    rows = [{**row, "race_key": t["race_key"], "race_date": t["race_date"], "venue_code": t["venue_code"]} for t in sets for row in t["rows"]]
    result = []
    for rule in rules():
        key = rule["id"]
        grouped = {label: [r for r in rows if r["matches"][key] is value] for label, value in (("true", True), ("false", False), ("unknown", None))}
        item = {**rule, "groups": {k: counts(v) for k, v in grouped.items()},
                "annual": [{"year": y, "groups": {k: counts([r for r in v if r["race_date"][:4] == y]) for k, v in grouped.items()}} for y in sorted({r["race_date"][:4] for r in rows})],
                "venues": {venue: {k: counts([r for r in v if r["venue_code"] == venue]) for k, v in grouped.items()} for venue in sorted({r["venue_code"] for r in rows})},
                "members": {k: [{field: r.get(field) for field in ("race_key", "race_date", "horse_id", "horse_no", "horse_name", "finish_rank")} for r in v] for k, v in grouped.items()}}
        if "parent_condition" in rule:
            item["rescue_breakdown"] = {status: counts([r for r in rows if r["rescue"][key]["status"] == status])
                                        for status in ("通常残す", "親条件不明", "救済", "救済不明", "割引候補")}
        result.append(item)
    return result


def combine(base: dict, evidence: list[dict], rule_index: int, mode: str) -> dict:
    """単一複合条件の差分だけを使用し、親条件との二重加点を避ける。"""
    if mode == "baseline":
        return {**base, "pattern": "baseline"}
    rule = rules()[rule_index]
    lookup = {r["horse_id"]: r["deltas"][rule_index] for r in evidence}
    scores = [(math.log(r["probability_top3"]/(1-r["probability_top3"]))+.5*lookup[r["horse_id"]])
              if mode == "integrated" else lookup[r["horse_id"]] for r in base["runners"]]
    rows = [{**r, "probability_top3": p} for r, p in zip(base["runners"], probabilities(scores), strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    return {**base, "pattern": mode+":"+rule["id"], "runners": rows}


def select(annual: list[dict], sets: list[dict]) -> dict:
    """開発年だけで捕捉非悪化と支持数を確認し、51方式から選ぶ。"""
    names = sorted({r["pattern"] for r in annual if r["pattern"] != "uniform"})
    dev = {p: mean_metrics([r for r in annual if r["pattern"] == p and "2008" <= r["race_date"][:4] <= "2020"]) for p in names}
    support = {}
    for rule in rules():
        matched = [(t, r) for t in sets if t["race_date"][:4] <= "2020" for r in t["rows"] if r["matches"][rule["id"]] is True]
        support[rule["id"]] = {"runners": len(matched), "editions": len({t["race_key"] for t, _ in matched})}
    eligible = ["baseline"]
    for p in names:
        if p == "baseline":
            continue
        s = support[p.split(":", 1)[1]]
        if s["runners"] >= 20 and s["editions"] >= 5 and all(dev[p][k] >= dev["baseline"][k]-1e-12 for k in ("top3_captured", "top6_captured")):
            eligible.append(p)
    chosen = min(eligible, key=lambda p: (dev[p]["brier"], 0 if p == "baseline" else 1, p))
    return {"pattern": chosen, "selection_through": 2020, "eligible": eligible, "development": dev, "support": support}


def evaluate(sets: list[dict], baseline: list[dict], history: list[dict], targets: list[dict], config: dict) -> dict:
    """対象年以前の集計で51方式を比較し、選択後の既知5年を採否判定する。"""
    outcomes = {(r["race_key"], r["horse_id"]): r for r in targets if r["status"] == "active"}
    examples = []
    for target in sets:
        rows = []
        for row in target["rows"]:
            truth = outcomes[(target["race_key"], row["horse_id"])]
            rows.append({**row, **features(target, row, history, []), "finish_rank": truth.get("rank"),
                         "nonfinish_confirmed": truth.get("rank") is None and truth.get("abnormal_code") not in (None, "0")})
        examples.append({**target, "rows": rows})
    groups = {r["id"]: [r["id"]] for r in rules()}
    predictions, annual, evidence = [], [], []
    for i, target in enumerate(examples):
        if i < 5:
            continue
        ev = group_deltas(examples[:i], target, {**config, "groups": groups}, {"half_life": None, "pooling": "hierarchical", "shrinkage": 20})
        evidence.append({"race_key": target["race_key"], "prior_latest_date": examples[i-1]["race_date"], "rows": ev})
        base = next(p for p in baseline if p["race_key"] == target["race_key"] and p["pattern"] == "N+C+W")
        options = [(0, "baseline")]+[(j, mode) for j in range(25) for mode in ("rules_only", "integrated")]
        for index, mode in options:
            prediction = combine(base, ev, index, mode)
            predictions.append(prediction)
            annual.append({k: prediction[k] for k in ("pattern", "race_key", "race_date")} | metrics(prediction, target))
        uniform = {**base, "runners": [{**r, "probability_top3": 3/len(base["runners"])} for r in base["runners"]]}
        annual.append({"pattern": "uniform", "race_key": target["race_key"], "race_date": target["race_date"], **metrics(uniform, target)})
    choice = select(annual, examples)
    selected = choice["pattern"]
    comparison = compare(annual, selected, "baseline", {"development": [2008, 2020], "confirmation": [2021, 2025], "bootstrap_seed": 240, "bootstrap_repeats": 5000}) if selected != "baseline" else None
    usable = comparison is not None and comparison["reference_conditions_met"]
    return {"examples": examples, "predictions": predictions, "annual": annual, "evidence": evidence,
            "selection": choice, "comparison": comparison, "forecast_pattern": selected if usable else "baseline",
            "research_change_eligible": usable, "adopted": False, "independent_validation": False,
            "rules": rules(), "unavailable": UNAVAILABLE, "rule_records": summaries(examples)}
