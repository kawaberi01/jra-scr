"""概要: 同名重賞の固有4群を個別に選択し、別年度で固定比較する。
作成日: 2026-11-20
入力: 監査済み正規化履歴、研究設定、既存一般特徴設定。
出力: 特徴・根拠、30候補と2基準の予測、年度指標、選択・採否。
実行例: uv run python scripts/run_jra_specific_patterns.py --help
注意事項: オフライン専用。事後属性・不完全な海外履歴を含み、利益や校正を保証しない。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import json
import math
import random
import unicodedata

from .jra_conditions_refinement import candidate_prediction, group_deltas
from .jra_conditions_search import score_prediction
from .jra_graded_patterns import feature_values, surface
from .jra_race_conditions import public_runner, require, verified_conditions


def route_name(value: str) -> str | None:
    """前走名を明示的な対応表で分類し、未収録の名前を推定しない。"""
    if not value or not value.strip():
        return None
    name = "".join(unicodedata.normalize("NFKC", value).split())
    aliases = {
        "富士ステークス": "富士S", "富士S": "富士S",
        "スワンステークス": "スワンS", "スワンS": "スワンS",
        "MBS賞スワンステークス": "スワンS", "毎日放送賞スワンステークス": "スワンS",
        "毎日王冠": "毎日王冠", "天皇賞(秋)": "天皇賞秋", "天皇賞秋": "天皇賞秋",
        "スプリンターズステークス": "スプリンターズS", "スプリンターズS": "スプリンターズS",
        "安田記念": "安田記念",
    }
    return aliases.get(name, "その他")


def weight_valid(value) -> bool:
    """実斤量として妥当な有限kg値かを判定し、0を欠測から実値にしない。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 40 <= value <= 70


def specific_features(series: str, race: dict, runner: dict, history: list[dict]) -> dict:
    """当該日前の同一馬履歴だけから専用8特徴と参照範囲を作る。"""
    require(series in ("fukushima", "mile"), "specific_series")
    prior = sorted((h for h in history if h["horse_id"] == runner["horse_id"]
                    and h["race_date"] < race["race_date"] and h["status"] == "active"),
                   key=lambda h: (h["race_date"], h["race_key"]))
    require(len({h["race_date"] for h in prior}) == len(prior), "specific_same_day_history_conflict")
    values = dict.fromkeys(["prep_grade", "prep_distance", "last_rank", "layoff"] +
                          (["handicap", "handicap_change", "fukushima_2000", "small_course_middle"]
                           if series == "fukushima" else ["prep_route", "mile_graded", "same_stage", "mile_g1"]))
    w = runner.get("weight_carried")
    if series == "fukushima" and weight_valid(w):
        values["handicap"] = "53以下" if w <= 53 else "53超55以下" if w <= 55 else "55超57以下" if w <= 57 else "57超"
    previous = prior[-1] if prior else None
    if previous:
        gap = (date.fromisoformat(race["race_date"]) - date.fromisoformat(previous["race_date"])).days
        rank = previous.get("rank")
        values["last_rank"] = ("1着" if rank == 1 else "2〜3着" if rank <= 3 else "4〜5着" if rank <= 5 else "6着以下") if rank else None
        values["layoff"] = "1〜28日" if gap <= 28 else "29〜56日" if gap <= 56 else "57〜112日" if gap <= 112 else "113日以上"
        if verified_conditions(previous):
            grade = previous.get("grade")
            values["prep_grade"] = grade if grade in ("A", "B", "C") else "非ABC"
            kind, distance = surface(previous["track_code"]), previous["distance"]
            if kind == "dirt":
                values["prep_distance"] = "ダート"
            elif kind == "turf":
                if series == "fukushima":
                    values["prep_distance"] = "1600以下" if distance <= 1600 else str(distance) if distance in (1800, 2000, 2200) else "その他"
                else:
                    values["prep_distance"] = "1200以下" if distance <= 1200 else str(distance) if distance in (1400, 1600, 1800) else "2000以上" if distance >= 2000 else "その他"
        good = [h for h in prior if h.get("rank") and h["rank"] <= 3]
        if series == "fukushima":
            pw = previous.get("weight_carried")
            if weight_valid(w) and weight_valid(pw):
                change = w - pw
                values["handicap_change"] = "-1以下" if change <= -1 else "1以上" if change >= 1 else "-1超1未満"
            values["fukushima_2000"] = "確認あり" if any(h["venue_code"] == "03" and h["distance"] == 2000 and surface(h["track_code"]) == "turf" for h in good) else "収録内確認なし"
            values["small_course_middle"] = "確認あり" if any(h["venue_code"] in ("01", "02", "03", "10") and 1800 <= h["distance"] <= 2200 and surface(h["track_code"]) == "turf" for h in good) else "収録内確認なし"
        else:
            values["prep_route"] = route_name(previous.get("race_name", ""))
            mile = [h for h in prior if h["distance"] == 1600 and surface(h["track_code"]) == "turf"]
            graded = [h for h in mile if h.get("grade") in ("A", "B", "C") and h.get("rank") and h["rank"] <= 3]
            values["mile_graded"] = "確認あり" if graded else "収録内確認なし" if all(verified_conditions(h) for h in mile) else None
            g1 = [h for h in graded if h["grade"] == "A"]
            values["mile_g1"] = "勝利" if any(h["rank"] == 1 for h in g1) else "2〜3着のみ" if g1 else "収録内確認なし" if all(verified_conditions(h) for h in mile) else None
            values["same_stage"] = "確認あり" if any(h["venue_code"] == race["venue_code"] and h["distance"] == race["distance"] and h["track_code"] == race["track_code"] for h in good) else "収録内確認なし"
    return {"values": values, "history_count": len(prior), "latest_date": previous["race_date"] if previous else None,
            "previous": {k: previous.get(k) for k in ("race_key", "race_name", "grade", "distance", "track_code", "weight_carried", "rank")} if previous else None}


def make_examples(data: dict, series: str, config: dict) -> tuple[list[dict], list[dict], dict]:
    """対象条件とIDを検査し、固有・一般特徴を結果から分離して返す。"""
    definition = config["series"][series]
    history = defaultdict(list)
    identities = set()
    for row in data["history"]:
        identity = (row["race_key"], row["horse_id"])
        require(identity not in identities, "specific_duplicate_history")
        identities.add(identity)
        history[row["horse_id"]].append(row)
    grouped = defaultdict(list)
    for row in data["target_rows"]:
        grouped[row["race_key"]].append(row)
    specific, general, missing = [], [], Counter()
    require(len(data["targets"]) == 23, "specific_23_editions")
    require({r["race_date"][:4] for r in data["targets"]} == {str(y) for y in range(2003, 2026)}, "specific_years")
    for target in sorted(data["targets"], key=lambda r: r["race_date"]):
        metadata = json.loads(target["metadata"])
        conditions = data["race_conditions"][target["race_key"]]
        require(metadata["race_name"] in definition["aliases"] and target["venue_code"] in definition["venues"]
                and int(metadata["distance_raw"]) == definition["distance"] and surface(metadata["track_code"]) == "turf"
                and conditions["grade"] == definition["grade"] and conditions["weight_rule"] == definition["weight_rule"], "specific_target_scope")
        race = {"race_key": target["race_key"], "race_date": target["race_date"], "race_name": metadata["race_name"],
                "venue_code": target["venue_code"], "distance": definition["distance"], "track_code": metadata["track_code"], "evaluation_eligible": True}
        rows = [r for r in grouped[target["race_key"]] if r["status"] == "active"]
        require(4 <= len(rows) <= 18 and len({r["horse_id"] for r in rows}) == len(rows) and len({r["horse_no"] for r in rows}) == len(rows), "specific_roster")
        require(sum(bool(r.get("rank") and r["rank"] <= 3) for r in rows) == 3, "specific_three_results")
        sp, ge = [], []
        for row in rows:
            require(len(row["horse_id"]) == 10 and row["horse_id"].isdigit() and weight_valid(row["weight_carried"]), "specific_runner_identity")
            require(all(row[k] == race[k] for k in ("race_key", "race_date", "venue_code", "distance", "track_code")), "specific_row_scope")
            features = specific_features(series, race, row, history[row["horse_id"]])
            missing.update(k for k, v in features["values"].items() if v is None)
            common = {**public_runner(row), "outcome": {"top3": bool(row.get("rank") and row["rank"] <= 3)}}
            sp.append({**common, **features})
            ge.append({**common, "values": feature_values(race, row, history[row["horse_id"]])})
        specific.append({**race, "rows": sp})
        general.append({**race, "rows": ge})
    return specific, general, dict(missing)


def candidates(config: dict, series: str) -> list[dict]:
    """4群の15非空部分集合を単独・固定補助混合の30候補へ展開する。"""
    groups = list(config["series"][series]["groups"])
    require(len(groups) == 4, "specific_four_groups")
    return [{"pattern": f"S{mask:02d}-{'G' if blend else 'only'}", "family": "specific", "mask": mask,
             "blend": blend, "weights": [int(bool(mask & (1 << i))) for i in range(4)],
             "group_count": mask.bit_count(), "groups": [g for i, g in enumerate(groups) if mask & (1 << i)], "scale": 1}
            for mask in range(1, 16) for blend in (False, True)]


def predict(target: dict, prior: list[dict], cfg: dict, candidate: dict) -> tuple[dict, list[dict]]:
    """既存のカテゴリ縮約・確率正規化を使い、当該結果は参照しない。"""
    parameters = {"half_life": None, "pooling": "hierarchical", "shrinkage": 20, **candidate}
    evidence = group_deltas(prior, target, cfg, parameters)
    return candidate_prediction(evidence, target, parameters), evidence


def capture(rows: list[dict], truth: dict, count: int) -> float:
    """同率の境界を公平配分して上位指定頭数の好走捕捉を算出する。"""
    total, start = 0., 0
    while start < len(rows):
        end = start + 1
        while end < len(rows) and abs(rows[end]["probability_top3"] - rows[start]["probability_top3"]) <= 1e-12:
            end += 1
        slots = max(0, min(count, end) - start)
        total += slots * sum(truth[r["horse_no"]] for r in rows[start:end]) / (end-start)
        start = end
    return total


def metrics(prediction: dict, target: dict) -> dict:
    """既存Brier等に同率公平な上位6頭捕捉を加える。"""
    result = score_prediction(prediction, target)
    truth = {r["horse_no"]: int(r["outcome"]["top3"]) for r in target["rows"]}
    return {**result, "top6_captured": capture(prediction["runners"], truth, 6)}


def mean_metrics(rows: list[dict]) -> dict:
    """出走頭数で重み付けせず、開催を等配分して集計する。"""
    require(bool(rows), "specific_empty_metrics")
    return {"races": len(rows), **{k: sum(r[k] for r in rows)/len(rows) for k in
                                  ("brier", "logloss", "top1_top3_hit", "top3_captured", "top6_captured")}}


def select_candidate(annual: list[dict], options: list[dict], config: dict) -> dict:
    """開発年度だけで選択し、同値なら少数群・単独・mask順にする。"""
    lo, hi = config["development"]
    scores = {}
    for c in options:
        rows = [r for r in annual if r["pattern"] == c["pattern"] and lo <= int(r["race_date"][:4]) <= hi]
        require(len(rows) == hi-lo+1, "specific_complete_development")
        scores[c["pattern"]] = sum(r["brier"] for r in rows)/len(rows)
    best = min(scores.values())
    chosen = min((c for c in options if scores[c["pattern"]] <= best+1e-12), key=lambda c: (c["group_count"], c["blend"], c["mask"]))
    return {"candidate": chosen, "development_brier": scores, "selection_through": str(hi)}


def confirmation(annual: list[dict], selected: str, config: dict) -> dict:
    """固定候補と一般基準の最終年差だけで、仕様の採用基準を判定する。"""
    lo, hi = config["confirmation"]
    by_pattern = {p: sorted([r for r in annual if r["pattern"] == p and lo <= int(r["race_date"][:4]) <= hi], key=lambda r: r["race_date"])
                  for p in (selected, "general", "uniform")}
    require(all(len(rows) == hi-lo+1 for rows in by_pattern.values()), "specific_confirmation_shape")
    first, second = by_pattern[selected], by_pattern["general"]
    require([r["race_key"] for r in first] == [r["race_key"] for r in second], "specific_confirmation_pairing")
    differences = [a["brier"]-b["brier"] for a, b in zip(first, second, strict=True)]
    rng = random.Random(config["bootstrap_seed"])
    draws = sorted(sum(rng.choices(differences, k=len(differences)))/len(differences) for _ in range(config["bootstrap_repeats"]))
    interval = [draws[int(.025*(len(draws)-1))], draws[int(.975*(len(draws)-1))]]
    summaries = {p: mean_metrics(rows) for p, rows in by_pattern.items()}
    a, b, u = summaries[selected], summaries["general"], summaries["uniform"]
    checks = {"brier_improvement_1pct": a["brier"] <= .99*b["brier"], "logloss_not_worse": a["logloss"] <= b["logloss"],
              "majority_years_improve": sum(d < 0 for d in differences) >= 3, "top3_not_worse": a["top3_captured"] >= b["top3_captured"]-1e-12,
              "interval_upper_below_zero": interval[1] < 0, "not_worse_than_uniform": a["brier"] <= u["brier"]}
    return {"summaries": summaries, "checks": checks, "adopted": all(checks.values()), "interval95": interval,
            "brier_relative_improvement": 1-a["brier"]/b["brier"], "improved_years": sum(d < 0 for d in differences),
            "bootstrap_repeats": config["bootstrap_repeats"], "bootstrap_seed": config["bootstrap_seed"],
            "annual": by_pattern}


def evaluate(data: dict, series: str, config: dict, general_config: dict) -> dict:
    """開発選択を先に固定し、後続5年を再選択せずに比較・保存する。"""
    require(config["minimum_prior_races"] == 5 and config["shrinkage"] == 20
            and config["specific_fraction"] == 2/3 and config["development"] == [2008, 2020]
            and config["confirmation"] == [2021, 2025] and general_config["shrinkage"] == 20,
            "specific_fixed_protocol")
    specific, general, missing = make_examples(data, series, config)
    options = candidates(config, series)
    scfg = {**general_config, "groups": config["series"][series]["groups"]}
    predictions, annual, evidence = [], [], []
    selection = None
    for index, target in enumerate(specific):
        year = int(target["race_date"][:4])
        if index < config["minimum_prior_races"]:
            continue
        if year == config["confirmation"][0]:
            selection = select_candidate(annual, options, config)
        gp, ge = predict(general[index], general[:index], general_config,
                         {"pattern": "general", "family": "baseline", "weights": [1]*5, "scale": 1})
        _, se = predict(target, specific[:index], scfg, options[0])
        evidence.append({"race_key": target["race_key"], "specific": se, "general": ge})
        local = [gp]
        general_p = {r["horse_no"]: r["probability_top3"] for r in gp["runners"]}
        for c in options:
            p = candidate_prediction(se, target, c)
            if c["blend"]:
                for row in p["runners"]:
                    row["probability_top3"] = (2*row["probability_top3"]+general_p[row["horse_no"]])/3
                p["runners"].sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
            local.append(p)
        up = {**gp, "pattern": "uniform", "runners": [{**r, "probability_top3": 3/len(gp["runners"])} for r in gp["runners"]]}
        up["runners"].sort(key=lambda r: int(r["horse_no"]))
        local.append(up)
        for p in local:
            require(abs(sum(r["probability_top3"] for r in p["runners"])-3) < 1e-8 and all(0 <= r["probability_top3"] <= 1 for r in p["runners"]), "specific_probability_contract")
            annual.append({"pattern": p["pattern"], "race_key": target["race_key"], "race_date": target["race_date"],
                           "venue_code": target["venue_code"], **metrics(p, target)})
            predictions.append(p)
    require(selection is not None and len(predictions) == 576, "specific_prediction_count")
    chosen = selection["candidate"]["pattern"]
    result = confirmation(annual, chosen, config)
    return {"protocol": config["protocol"], "series": series, "race_name": config["series"][series]["name"],
            "selection": selection, "confirmation": result, "predictions": predictions, "annual": annual,
            "evidence": evidence, "examples": specific, "missing_features": missing,
            "venue_summary": {v: {p: mean_metrics([r for r in annual if r["venue_code"] == v and r["pattern"] == p])
                                   for p in (chosen, "general", "uniform")}
                              for v in sorted({r["venue_code"] for r in annual})}}
