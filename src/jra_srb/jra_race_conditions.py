"""概要: 同名重賞の既知条件を集計し、説明付き順位と時系列評価を作る。
作成日: 2026-11-08。
入力: 非秘密の条件設定、解析済み競走・出走馬・過去履歴、任意の事前カード。
出力: メモリ内の条件比較、推定3着内確率、根拠、検証指標。
実行例: uv run python scripts/run_jra_race_conditions.py analyze --help
注意事項: DB・外部通信・学習・購入を行わない。確率は未校正の研究推定値。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta, timezone
import json
import math
from pathlib import Path

from .jra_research_contracts import ResearchError, digest, horse_number, timestamp


FEATURE_LABELS = {
    "age": "年齢", "frame": "枠", "previous_race": "DB内直近走の名称",
    "previous_grade": "直近走の格コード", "previous_weight_rule": "直近走の重量方式コード",
    "previous_symbol": "直近走の競走記号コード", "previous_rank": "直近走の着順",
    "interval": "DB内直近走からの間隔", "previous_distance": "直近走距離",
    "distance_change": "距離変更", "weight_change": "斤量変更",
    "repeat_top3": "同名レース好走", "course_distance_top3": "同場同距離好走",
    "graded_top3": "重賞好走",
}
PUBLIC_RUNNER_FIELDS = (
    "horse_id", "horse_name", "horse_no", "age", "sex", "frame_no",
    "weight_carried", "jockey", "trainer", "status", "latest_race_date",
)
PUBLIC_RACE_FIELDS = ("race_key", "race_date", "race_name", "venue_code", "distance", "track_code")


def require(condition: bool, reason: str) -> None:
    """契約不成立時に秘密を含まない固定理由で停止する。"""
    if not condition:
        raise ResearchError(reason)


def load_config(path: str | Path) -> dict:
    """初版の対象・上限・条件構成を厳密に読み、未知設定を拒否する。"""
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    keys = {"schema_version", "profile_id", "race_name", "source_key", "snapshot_id", "first_year",
            "last_year", "minimum_prior_races", "shrinkage", "groups", "limits"}
    require(set(value) == keys and value["schema_version"] == 1, "conditions_config_keys")
    require(value["profile_id"] == "elizabeth-known-conditions-v1" and value["race_name"] == "エリザベス女王杯",
            "conditions_profile")
    require(value["snapshot_id"] == 31 and value["source_key"] == "prediction-full-20261008", "conditions_source")
    require(all(type(value[k]) is int for k in ("first_year", "last_year", "minimum_prior_races", "shrinkage")),
            "conditions_config_types")
    require(2003 <= value["first_year"] <= value["last_year"] <= 2025 and value["minimum_prior_races"] >= 5
            and value["shrinkage"] > 0, "conditions_config_range")
    names = [f for group in value["groups"].values() for f in group]
    require(len(value["groups"]) == 5 and len(names) == len(set(names)) and set(names) == set(FEATURE_LABELS),
            "conditions_feature_contract")
    require(set(value["limits"]) == {"query_timeout_seconds", "max_history_rows", "max_raw_rows", "max_ra_metadata_rows"}, "conditions_limits")
    for name, maximum in (("query_timeout_seconds", 90), ("max_history_rows", 20000), ("max_raw_rows", 20000),
                          ("max_ra_metadata_rows", 100000)):
        require(type(value["limits"][name]) is int and 0 < value["limits"][name] <= maximum, "conditions_limit_value")
    return value


def public_race(race: dict) -> dict:
    """当該結果や実現した馬場を持たない、許可された事前属性だけを返す。"""
    return {k: race[k] for k in PUBLIC_RACE_FIELDS}


def public_runner(runner: dict) -> dict:
    """当該着順を遮断し、公開属性だけの馬データを返す。"""
    return {k: runner.get(k) for k in PUBLIC_RUNNER_FIELDS}


def validate_race(race: dict) -> None:
    """日付・競走ID・距離・活動馬の同定と重複を検査する。"""
    day = date.fromisoformat(race["race_date"])
    key = race["race_key"]
    require(isinstance(key, str) and len(key) == 12 and key.isascii() and key.isdigit()
            and key[:8] == day.strftime("%Y%m%d") and key[8:10] == race["venue_code"], "conditions_race_identity")
    require(race["race_name"] == "エリザベス女王杯" and race["distance"] == 2200
            and race["venue_code"] in ("08", "09") and 10 <= int(race["track_code"]) <= 22, "conditions_race_scope")
    active = [r for r in race["runners"] if r.get("status") == "active"]
    require(all(r.get("status") in ("active", "excluded") for r in race["runners"]), "conditions_runner_status")
    require(4 <= len(active) <= 18, "conditions_roster_size")
    require(len({horse_number(r["horse_no"]) for r in active}) == len(active), "conditions_duplicate_number")
    identities = [r["horse_id"] for r in active]
    require(all(isinstance(v, str) and v.isascii() and v.isdigit() and len(v) == 10 and int(v) > 0 for v in identities)
            and len(set(identities)) == len(active), "conditions_duplicate_or_missing_horse")
    for r in active:
        require(type(r["age"]) is int and 3 <= r["age"] <= 15 and r["sex"] == "2", "conditions_runner_age_sex")
        require(type(r["frame_no"]) is int and 1 <= r["frame_no"] <= 8, "conditions_runner_frame")
        require(isinstance(r["weight_carried"], (int, float)) and not isinstance(r["weight_carried"], bool)
                and math.isfinite(r["weight_carried"]) and 40 <= r["weight_carried"] <= 70, "conditions_runner_weight")


def verified_conditions(row: dict) -> bool:
    """条件の確認状態を返し、旧入力だけRA検証フラグへフォールバックする。"""
    return row.get("conditions_verified", row.get("ra_verified")) is True


def make_features(race: dict, runner: dict, history: list[dict]) -> dict:
    """対象日前の保存履歴だけでカテゴリを生成する。同日・未来走と当該結果は使わない。

    Args:
        race: 当該競走の許可属性。
        runner: 当該馬の許可属性。
        history: 馬ID付き保存過去走。地方・海外等の網羅は保証しない。
    Returns:
        条件値、参照した履歴日、履歴件数。未観測値はNone。
    """
    current, horse = public_race(race), public_runner(runner)
    prior = sorted((h for h in history if h["horse_id"] == horse["horse_id"]
                    and h["race_date"] < current["race_date"] and h.get("status") == "active"),
                   key=lambda h: (h["race_date"], h["race_key"]))
    require(len({h["race_key"] for h in prior}) == len(prior), "conditions_duplicate_history")
    values = dict.fromkeys(FEATURE_LABELS)
    values["age"] = str(horse["age"]) if horse["age"] <= 5 else "6歳以上"
    values["frame"] = "内1〜3" if horse["frame_no"] <= 3 else "中4〜6" if horse["frame_no"] <= 6 else "外7〜8"
    if prior:
        previous = prior[-1]
        gap = (date.fromisoformat(current["race_date"]) - date.fromisoformat(previous["race_date"])).days
        rank = previous.get("rank")
        distance = previous["distance"]
        values.update(previous_race=previous.get("race_name") or None, previous_grade=previous.get("grade") or None,
                      previous_weight_rule=previous.get("weight_rule") or None, previous_symbol=previous.get("symbol") or None,
                      previous_rank=("1〜3着" if rank <= 3 else "4〜5着" if rank <= 5 else "6着以下") if rank else None,
                      interval="28日以下" if gap <= 28 else "29〜56日" if gap <= 56 else "57日以上",
                      previous_distance="1800m以下" if distance <= 1800 else "1801〜2000m" if distance <= 2000
                      else "2001〜2200m" if distance <= 2200 else "2201m以上",
                      distance_change="延長" if current["distance"] > distance else "短縮" if current["distance"] < distance else "同距離")
        if previous.get("weight_carried") is not None:
            delta = horse["weight_carried"] - previous["weight_carried"]
            values["weight_change"] = "増" if delta > .01 else "減" if delta < -.01 else "同"
        good = [h for h in prior if h.get("rank") and h["rank"] <= 3]
        values["repeat_top3"] = "確認あり" if any(h["race_name"] == current["race_name"] for h in good) else "確認なし"
        values["course_distance_top3"] = "確認あり" if any(h["venue_code"] == current["venue_code"]
            and h["distance"] == current["distance"] and (int(h["track_code"]) < 23) for h in good) else "確認なし"
        # 原RAまたは明示的に照合した公式条件が不明なら、非重賞と確定しない。
        values["graded_top3"] = "確認あり" if any(h.get("grade") in ("A", "B", "C") for h in good) else (
            "確認なし" if all(verified_conditions(h) for h in prior) else None)
    return {"values": values, "history_count": len(prior), "latest_stored_race": prior[-1]["race_date"] if prior else None}


def examples(dataset: dict) -> list[dict]:
    """各年の許可特徴と結果を別領域に保持し、全出走行を対応させる。"""
    result, seen = [], set()
    for race in sorted(dataset["races"], key=lambda r: r["race_date"]):
        validate_race(race)
        require(race["race_key"] not in seen, "conditions_duplicate_race")
        seen.add(race["race_key"])
        rows = []
        for runner in race["runners"]:
            if runner["status"] != "active":
                continue
            features = make_features(race, runner, dataset["history"])
            rows.append({**public_runner(runner), **features, "outcome": {"rank": runner.get("rank"),
                         "top3": bool(runner.get("rank") and runner["rank"] <= 3)}})
        result.append({**public_race(race), "conditions": race.get("conditions", {}), "rows": rows,
                       "excluded": [r for r in race["runners"] if r["status"] != "active"],
                       "evaluation_eligible": sum(r["outcome"]["top3"] for r in rows) == 3})
    return result


def _logit(p: float) -> float:
    """数値境界を保護した対数オッズを返す。"""
    p = min(1 - 1e-9, max(1e-9, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """指数overflowを避けてロジスティック関数を計算する。"""
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def probabilities(scores: list[float]) -> list[float]:
    """各馬の推定周辺確率を0〜1、合計3へ調整する。校正や同時確率の証明ではない。"""
    require(4 <= len(scores) <= 18 and all(math.isfinite(v) for v in scores), "conditions_score_shape")
    lo, hi = -100.0 - max(scores), 100.0 - min(scores)
    for _ in range(100):
        middle = (lo + hi) / 2
        if sum(_sigmoid(s + middle) for s in scores) < 3:
            lo = middle
        else:
            hi = middle
    return [_sigmoid(s + (lo + hi) / 2) for s in scores]


def predict(prior: list[dict], target: dict, config: dict, disabled: str | None = None) -> dict:
    """過去の同名競走の条件集計を縮約し、結果を参照せず各馬を評価する。"""
    history = [r for r in prior if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
    require(len(history) >= config["minimum_prior_races"], "conditions_insufficient_prior_races")
    observed = [(race, row) for race in history for row in race["rows"]]
    b = sum(row["outcome"]["top3"] for _, row in observed) / len(observed)
    same = [(race, row) for race, row in observed if race["venue_code"] == target["venue_code"]]
    strength = config["shrinkage"]
    base = (sum(row["outcome"]["top3"] for _, row in same) + strength * b) / (len(same) + strength)
    records, scores = [], []
    for row in target["rows"]:
        groups = []
        for group, feature_names in config["groups"].items():
            evidence = []
            for name in feature_names:
                value = row["values"][name]
                matched = [(r, h) for r, h in observed if value is not None and h["values"][name] == value]
                if not matched:
                    continue
                success = sum(h["outcome"]["top3"] for _, h in matched)
                global_rate = (success + strength * b) / (len(matched) + strength)
                local = [(r, h) for r, h in matched if r["venue_code"] == target["venue_code"]]
                local_success = sum(h["outcome"]["top3"] for _, h in local)
                rate = (local_success + strength * global_rate) / (len(local) + strength)
                evidence.append({"feature": name, "label": FEATURE_LABELS[name], "value": value,
                    "n": len(matched), "top3": success, "years": len({r["race_date"][:4] for r, _ in matched}),
                    "same_venue_n": len(local), "same_venue_top3": local_success, "smoothed_rate": rate,
                    "delta": _logit(rate) - _logit(base)})
            delta = sum(e["delta"] for e in evidence) / len(evidence) if evidence else 0.0
            groups.append({"group": group, "delta": delta, "evidence": evidence,
                           "unknown_count": sum(row["values"][f] is None for f in feature_names)})
        score = _logit(3 / len(target["rows"])) + sum(g["delta"] for g in groups if g["group"] != disabled) / len(groups)
        scores.append(score)
        records.append({"horse_no": row["horse_no"], "horse_name": row["horse_name"], "horse_id": row["horse_id"],
                        "history_count": row["history_count"], "latest_stored_race": row["latest_stored_race"],
                        "features": row["values"], "groups": groups})
    estimated = probabilities(scores)
    for index, record in enumerate(records):
        record["probability_top3"] = estimated[index]
        impacts = []
        for group in config["groups"]:
            without = [s - next(g["delta"] for g in r["groups"] if g["group"] == group) / len(config["groups"])
                       if group != disabled else s for s, r in zip(scores, records, strict=True)]
            impacts.append({"group": group, "probability_difference_pp": 100 * (estimated[index] - probabilities(without)[index])})
        record["explanations"] = sorted(impacts, key=lambda x: abs(x["probability_difference_pp"]), reverse=True)[:3]
    records.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    for position, row in enumerate(records, 1):
        row["display_order"] = position
    return {"race_key": target["race_key"], "race_date": target["race_date"], "venue_code": target["venue_code"],
            "prior_races": len(history), "prior_latest_date": max(r["race_date"] for r in history),
            "probability_kind": "uncalibrated_top3_marginals", "availability": "research_only", "runners": records}


def _metrics(prediction: dict, target: dict) -> dict:
    """同じ出走集合の二値Brier・logloss・上位捕捉を計算する。"""
    truth = {r["horse_no"]: r["outcome"]["top3"] for r in target["rows"]}
    pairs = [(r["probability_top3"], int(truth[r["horse_no"]])) for r in prediction["runners"]]
    return {"races": 1, "runners": len(pairs), "brier": sum((p - y) ** 2 for p, y in pairs) / len(pairs),
            "logloss": -sum(y * math.log(max(p, 1e-12)) + (1-y) * math.log(max(1-p, 1e-12)) for p, y in pairs) / len(pairs),
            "top1_top3_hit": float(pairs[0][1]), "top3_captured": sum(y for _, y in pairs[:3])}


def aggregate(metrics: list[dict]) -> dict:
    """確率損失は出走行加重、順位指標は開催均等で集計する。"""
    if not metrics:
        return {"races": 0, "runners": 0, "brier": None, "logloss": None, "top1_top3_hit": None, "top3_captured": None}
    n = sum(m["runners"] for m in metrics)
    return {"races": len(metrics), "runners": n,
            **{key: sum(m[key] * m["runners"] for m in metrics) / n for key in ("brier", "logloss")},
            **{key: sum(m[key] for m in metrics) / len(metrics) for key in ("top1_top3_hit", "top3_captured")}}


def analyze(dataset: dict, config: dict) -> dict:
    """固定条件の年次比較・全グループ除去比較・一律基準を漏れなく作る。"""
    require(dataset.get("schema_version") == 1 and dataset.get("race_name") == config["race_name"], "conditions_dataset_contract")
    rows = examples(dataset)
    variants = ["full", "uniform", *["without:" + g for g in config["groups"]]]
    annual, predictions, excluded = [], [], []
    for target in rows:
        prior = [r for r in rows if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
        if not target["evaluation_eligible"] or len(prior) < config["minimum_prior_races"]:
            excluded.append({"race_key": target["race_key"], "reason": "warmup" if target["evaluation_eligible"] else "top3_count_not_three"})
            continue
        full = predict(prior, target, config)
        predictions.append(full)
        for variant in variants:
            if variant == "uniform":
                n = len(target["rows"])
                # 同確率の馬番順選択を技能とせず、順位指標は無作為選択の期待値とする。
                prediction = {"runners": [{"horse_no": r["horse_no"], "probability_top3": 3/n} for r in target["rows"]]}
                metric = _metrics(prediction, target)
                metric.update(top1_top3_hit=3/n, top3_captured=9/n)
            else:
                prediction = full if variant == "full" else predict(prior, target, config, variant.split(":", 1)[1])
                metric = _metrics(prediction, target)
            annual.append({"variant": variant, "race_key": target["race_key"], "race_date": target["race_date"],
                           "venue_code": target["venue_code"], **metric})
    summary = {v: {"all": aggregate([m for m in annual if m["variant"] == v]),
                   **{venue: aggregate([m for m in annual if m["variant"] == v and m["venue_code"] == venue])
                      for venue in ("08", "09")}} for v in variants}
    return {"protocol": config["profile_id"], "config_sha256": digest(config), "historical_status": "retrospective_research",
            "probability_kind": "uncalibrated_top3_marginals", "comparison_rows": rows, "predictions": predictions,
            "annual_metrics": annual, "summary": summary, "excluded": excluded,
            "limitations": ["過去属性と実出走集合は事後版。厳密な発走前再現ではない。", "前走はDB内直近確認走。海外・地方・収録外履歴の不足がある。",
                            "条件率と重みは固定方式。独立した未知期間での優位・校正・購入利益は未証明。"]}


def validate_card(card: dict, config: dict) -> None:
    """将来カードの許可列・観測時刻・対象を検査し、結果の混入を拒否する。"""
    require(set(card) == set(PUBLIC_RACE_FIELDS) | {"runners", "observed_at", "start_at"}, "conditions_card_keys")
    require(all(set(r) <= set(PUBLIC_RUNNER_FIELDS) for r in card["runners"]), "conditions_card_result_rejected")
    observed, start = timestamp(card["observed_at"]), timestamp(card["start_at"])
    require(observed < start and start.astimezone(timezone(timedelta(hours=9))).date().isoformat()
            == card["race_date"], "conditions_card_time")
    require(card["race_name"] == config["race_name"], "conditions_card_name")
    validate_race(card)


def predict_card(dataset: dict, card: dict, config: dict) -> dict:
    """明示カードを評価し、独立した最新性が未証明なら参考出力に留める。"""
    validate_card(card, config)
    observed_day = timestamp(card["observed_at"]).astimezone(timezone(timedelta(hours=9))).date().isoformat()
    # 発走より前でも、カード観測後の履歴は使用しない。同日走も保守的に除外する。
    available_history = [h for h in dataset["history"] if h["race_date"] < observed_day]
    prior = [r for r in examples(dataset) if r["race_date"] < observed_day]
    rows = [{**public_runner(r), **make_features(card, r, available_history)}
            for r in card["runners"] if r.get("status") == "active"]
    target = {**public_race(card), "rows": rows}
    output = predict(prior, target, config)
    output.update(availability="reference_only", observed_at=card["observed_at"], start_at=card["start_at"])
    output["freshness"] = [{"horse_no": r["horse_no"], "latest_stored_race": r["latest_stored_race"],
        "declared_latest_race": r.get("latest_race_date"),
        "status": "matches_declared" if r.get("latest_race_date") and r["latest_race_date"] == r["latest_stored_race"] else "unverified_or_mismatch"}
        for r in rows]
    output["limitations"] = ["入力カードの公表時点と全履歴の独立検証は未完了。購入推奨ではない。"]
    return output
