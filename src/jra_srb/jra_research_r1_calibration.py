"""概要: 保存R1の確率校正と的中条件付き価格補正を固定期間で比較する。
作成日: 2026-10-18
入力: spec180、保存R1、統合SQL年別RA/SE・T30市場・確定馬連払戻。
出力: 新規研究runの校正係数・価格モデル・予測・集計・検証。
実行例: uv run --frozen --extra ml python scripts/run_jra_r1_calibration.py
注意事項: SQL SELECTのみ。元R1の再fit・既定変更・原文複製・外部API送信なし。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import hashlib
from itertools import combinations
import json

import joblib
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest
from .jra_research_history import HistoryConfig
from .jra_research_resources import check_memory
from .jra_research_r1_live import BASELINE, LiveAnnualReader, load_model, read_json, require
from . import jra_research_tipster_experiment as prior
from . import jra_research_tipster_residual as residual
from . import jra_research_tipster_smoke as base
from . import jra_research_tipster_twenty as native


VARIANTS = ("C0", "C1", "C2")
POLICIES = ("P0", "P1")
PERIODS = ("calibration", "evaluation_2025", "evaluation_early", "evaluation_late", "reused_2026", "later_2026")
BINS = (0, .015, .03, .05, .1, .2, 1.0000001)
PRICE_BANDS = ((4, 10), (10, 20), (20, 40), (40, 80))
CONFIG = {"protocol": "spec180-r1-calibration-price-v1", "baseline_run": BASELINE,
          "calibration": ["2025-10-01", "2025-10-31"], "development": ["2025-11-01", "2025-12-31"],
          "price_fit": ["2024-01-01", "2025-09-30"], "later_evaluation": ["2026-09-01", "2026-10-04"],
          "variants": list(VARIANTS), "policies": list(POLICIES), "temperature_exponent_bounds": [.5, 2],
          "residual_shrink_bounds": [0, 1], "price_bands": list(PRICE_BANDS), "price_shrink_count": 50,
          "price_min_band_hits": 30, "price_min_total_hits": 100, "discount_bounds": [.5, 1],
          "probability_bins": list(BINS), "stake_yen": 600, "unseen_test": False,
          "default_changed": False, "base_model_refits": 0}


def period_for(day):
    """既存分割に、選択へ使用しない追加時系列期間だけを足す。"""
    return "later_2026" if CONFIG["later_evaluation"][0] <= day <= CONFIG["later_evaluation"][1] else prior.split(day)


def in_period(row, period):
    """期間別集計と、2026年前半の合算対象を判定する。"""
    value = row.get("period", row.get("split"))
    return value == period or period == "reused_2026" and value in ("evaluation_early", "evaluation_late")


def prepare(artifacts, baseline):
    """元研究の対象と追加期間を、同じ日付順のSQL履歴から一巡で作る。

    Notes:
        2003〜2025年は元readerを再利用しdigest一致を要求する。
        2026年だけ既存当日readerで10月4日まで拡張し、元対象の全損失と
        購入会計を後で照合する。同日結果はその日の全特徴の生成後に加える。
    """
    expected = {r["race_key"] for r in baseline["race_metrics"]}
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with prior.ExperimentMarketReader(config) as reader:
        rows = reader._small("r1_calibration:days", "SELECT DISTINCT race_date FROM history.races WHERE __migration_source_snapshot_id=? AND race_date>=? AND race_date<=? ORDER BY race_date", (31, "2024-01-01", "2026-10-04"))
    days = [r["race_date"] for r in rows if period_for(r["race_date"]) is not None]
    require(0 < len(days) <= 500, "r1_calibration_day_scope")
    states, target, years = native.States(), {}, {}
    with LiveAnnualReader(config) as reader:
        artifacts.write_json("preflight.json", reader.preflight())
        for year in range(2003, 2027):
            if year == 2026:
                raw, audit = reader.year_before(year, "2026-10-05")
            else:
                raw, audit = reader.year(year)
                require(audit["input_digest"] == baseline["coverage"]["years"][str(year)]["input_digest"], "r1_calibration_annual_input_changed")
            grouped = defaultdict(list)
            for key in sorted(raw):
                race, reason = native.parse_race(key, raw[key])
                if reason:
                    audit[reason] = audit.get(reason, 0) + 1
                else:
                    grouped[race["day"]].append(race)
            del raw
            for day, races in sorted(grouped.items()):
                for race in races:
                    audit["usable_races"] = audit.get("usable_races", 0) + 1
                    period = period_for(day)
                    if day not in days or (period not in ("train", "later_2026") and race["key"] not in expected):
                        continue
                    target[race["key"]] = {"x": residual.public_features(states, race), "runners": race["runners"]}
                for race in races:
                    states.update(race)
            years[str(year)] = audit
            artifacts.write_json("coverage.json", {"stage": "native_history", "years": years, "features_created": len(target)})
            print(json.dumps({"stage": "native_history", "year": year, "features_created": len(target)}), flush=True)
            del grouped
            gc.collect()
            check_memory(2147483648)
    del states
    records, excluded, streams = [], [], []
    empty = base.history._build_history_states([])
    with prior.ExperimentMarketReader(config) as reader:
        for offset in range(0, len(days), 4):
            races, rowsets = reader.selected(days[offset:offset + 4])
            converted, missing = base.sql_races(races, rowsets, [], state_provider=lambda _: empty)
            excluded.extend(missing)
            identities = {(r["race_key"], r["horse_no"]): r["horse_id"] for r in rowsets["history.entries"]}
            streams.append(reader.report["input_digest"])
            for data in converted:
                key, day = data["race_id"], data["race_date"]
                period = period_for(day)
                if period not in ("train", "later_2026") and key not in expected:
                    continue
                entry = target.get(key)
                if entry is None:
                    excluded.append({"race_key": key, "reason": "native_missing"})
                    continue
                runners, ranks = entry["runners"], data["result"]["ranks_by_horse"]
                if set(ranks) != {r["horse_no"] for r in runners} or any(ranks[r["horse_no"]] != r["rank"] or identities.get((key, r["horse_no"])) != r["horse_id"] for r in runners):
                    excluded.append({"race_key": key, "reason": "native_market_mismatch"})
                    continue
                pairs = list(combinations([r["horse_no"] for r in runners], 2))
                quotes = {tuple(sorted((r["horse_no_1"], r["horse_no_2"]), key=int)): r["odds"] for r in data["inputs"]["odds"]["T-30m"]["quinella"]["pairs"]}
                prices = np.asarray([quotes[p] for p in pairs])
                market = 1 / prices
                market /= market.sum()
                payouts = {tuple(sorted((r["horse_no_1"], r["horse_no_2"]), key=int)): r["payout"] for r in data["result"]["quinella_payout_per_100_yen"]}
                y = np.asarray([float(p in payouts) for p in pairs])
                if y.sum() != 1:
                    excluded.append({"race_key": key, "reason": "non_unique_target"})
                    continue
                records.append({"race_key": key, "race_date": day, "period": period, "venue": data["race"]["course"],
                                "x": entry["x"], "keys": pairs, "prices": prices, "market": market, "target": y, "payouts": payouts})
            if offset % 20 == 0:
                print(json.dumps({"stage": "market", "days_read": min(offset + 4, len(days)), "days_total": len(days), "adopted": len(records)}), flush=True)
    common = {r["race_key"] for r in records if r["period"] not in ("train", "later_2026")}
    require(common == expected and len(common) == 1787, "r1_calibration_reference_cohort_changed")
    coverage = {"years": years, "input_digest": digest({y: a["input_digest"] for y, a in years.items()}),
                "market_digest": digest(streams), "available_days": days,
                "adopted_by_split": dict(Counter(r["period"] for r in records)), "reference_races": len(common),
                "excluded": excluded, "sqlite_used": False, "later_period_not_certified_unseen": True}
    artifacts.write_json("coverage.json", coverage)
    return sorted(records, key=lambda r: (r["race_date"], r["race_key"])), coverage


def calibrated(record, model):
    """結果を参照せず、固定R1確率と市場に保存された校正係数を適用する。"""
    p = record["r1_probability"]
    if model["variant"] == "C0":
        return p.copy()
    if model["variant"] == "C1":
        return softmax(model["coefficient"] * np.log(p))
    require(model["variant"] == "C2", "r1_unknown_calibration")
    return softmax(np.log(record["market"]) + model["coefficient"] * (np.log(p) - np.log(record["market"])))


def fit_calibrator(records, variant):
    """R1と分離した2025年10月だけで1係数をfitし、基準値と端点も比較する。"""
    require(records and all(CONFIG["calibration"][0] <= r["race_date"] <= CONFIG["calibration"][1] for r in records), "r1_calibration_fit_boundary")
    info = {"variant": variant, "fit_races": len(records), "fit_through": max(r["race_date"] for r in records)}
    if variant == "C0":
        return {**info, "coefficient": 1.0}
    lower, upper = (.5, 2) if variant == "C1" else (0, 1)

    def objective(value):
        """競走を同じ重みとして校正期間の対数損失を計算する。"""
        model = {"variant": variant, "coefficient": float(value)}
        return float(np.mean([-r["target"] @ np.log(np.maximum(calibrated(r, model), 1e-15)) for r in records]))

    optimized = minimize_scalar(objective, bounds=(lower, upper), method="bounded", options={"xatol": 1e-8})
    require(optimized.success, "r1_calibration_optimizer_failed")
    candidates = (lower, upper, 1.0, float(optimized.x))
    ranked = sorted((objective(value), abs(value - 1), value) for value in candidates)
    coefficient = ranked[0][2]
    return {**info, "coefficient": float(coefficient), "calibration_logloss": ranked[0][0], "bounds": [lower, upper]}


def price_band(value):
    """固定価格帯を返し、対象外価格は補正対象にしない。"""
    return next((i for i, (low, high) in enumerate(PRICE_BANDS) if low <= value < high or i == 3 and value == high), None)


def fit_price_model(records):
    """R1学習期間の的中ペアだけから、価格帯別の保守的精算比率をfitする。

    Notes:
        的中条件付きの推定であり、全組合せの最終オッズの観測ではない。
        fit後に評価期間を使って係数や購入閾値を調整しない。
    """
    require(records and all(CONFIG["price_fit"][0] <= r["race_date"] <= CONFIG["price_fit"][1] for r in records), "r1_price_fit_boundary")
    values = []
    for r in records:
        winner = int(np.argmax(r["target"]))
        quote = float(r["prices"][winner])
        band = price_band(quote)
        if band is not None:
            values.append((band, quote, r["payouts"][r["keys"][winner]] / 100))
    available = len(values) >= CONFIG["price_min_total_hits"]
    ratio = sum(v[2] for v in values) / sum(v[1] for v in values) if values else 1.0
    bands = []
    for index, (low, high) in enumerate(PRICE_BANDS):
        subset = [v for v in values if v[0] == index]
        raw = sum(v[2] for v in subset) / sum(v[1] for v in subset) if subset else ratio
        estimate = (len(subset) * raw + 50 * ratio) / (len(subset) + 50) if len(subset) >= 30 else ratio
        discount = float(np.clip(estimate, .5, 1)) if available else 1.0
        bands.append({"low": low, "high": high, "hits": len(subset), "raw_settlement_ratio": raw, "discount": discount})
    return {"fit_races": len(records), "fit_through": max(r["race_date"] for r in records), "fit_hits": len(values),
            "available": available, "global_settlement_ratio": ratio, "bands": bands,
            "interpretation": "conditional_on_hit_not_all_pair_final_odds", "threshold_tuned_on_evaluation": False}


def discounts(prices, model):
    """価格だけから学習済み帯別係数を引き、範囲外は1を返す。"""
    return np.asarray([model["bands"][band]["discount"] if (band := price_band(float(v))) is not None else 1.0 for v in prices])


def select_pair(probabilities, prices, factors):
    """固定予算・価格帯・確率・期待倍率で最大1点を選び、結果は参照しない。"""
    ev = probabilities * prices * factors
    valid = np.flatnonzero((prices >= 4) & (prices <= 80) & (probabilities >= .015) & (ev >= 1.05))
    chosen = sorted(valid, key=lambda i: (-round(float(ev[i]), 12), int(i)))[:1]
    return int(chosen[0]) if chosen else None


def reliability(probabilities, target, selected=None):
    """確率帯別に件数・予測数・実的中数を集約し、個票を保存しない。"""
    indices = np.arange(len(target)) if selected is None else np.asarray(selected, dtype=int)
    groups = []
    for low, high in zip(BINS[:-1], BINS[1:], strict=True):
        chosen = indices[(probabilities[indices] >= low) & (probabilities[indices] < high)]
        groups.append({"low": low, "high": min(high, 1), "pairs": len(chosen),
                       "predicted_hits": float(probabilities[chosen].sum()), "hits": int(target[chosen].sum())})
    return groups


def aggregate_reliability(groups):
    """各競走の固定帯集計を足し、予測と実際の確率を併記する。"""
    result = []
    for index, (low, high) in enumerate(zip(BINS[:-1], BINS[1:], strict=True)):
        count = sum(g[index]["pairs"] for g in groups)
        predicted = sum(g[index]["predicted_hits"] for g in groups)
        hits = sum(g[index]["hits"] for g in groups)
        result.append({"low": low, "high": min(high, 1), "pairs": count, "predicted_hits": predicted, "hits": hits,
                       "mean_probability": predicted / count if count else None, "observed_rate": hits / count if count else None})
    return result


def paired_interval(rows, variant):
    """日単位でR1に対する損失差の区間を出し、ゼロ購入日も保持する。"""
    if not rows:
        return {"races": 0, "days": 0, "loss_delta_vs_r1": None, "loss_delta_95": None}
    daily = defaultdict(lambda: np.zeros(2))
    for r in rows:
        daily[r["race_date"]] += [r["loss"][variant] - r["loss"]["C0"], 1]
    values = np.asarray([v for _, v in sorted(daily.items())])
    indices = np.random.default_rng(180).integers(0, len(values), size=(2000, len(values)))
    sums = values[indices].sum(axis=1)
    return {"races": len(rows), "days": len(values), "loss_delta_vs_r1": float(values[:, 0].sum() / values[:, 1].sum()),
            "loss_delta_95": np.quantile(sums[:, 0] / sums[:, 1], [.025, .975]).tolist(), "replicates": 2000}


def price_diagnostic(records, name):
    """全競走の的中ペアの時点仮精算と実精算を比較し、母集団を明示する。"""
    values = []
    for r in records:
        winner = int(np.argmax(r["target"]))
        values.append((float(r["prices"][winner]) * 100, r["payouts"][r["keys"][winner]]))
    quote, actual = sum(v[0] for v in values), sum(v[1] for v in values)
    return {"period": name, "winning_pairs": len(values), "quoted_hit_payout_per_100_sum": quote,
            "actual_hit_payout_per_100_sum": actual, "settlement_ratio": actual / quote if quote else None,
            "fraction_below_quote": sum(v[1] < v[0] for v in values) / len(values) if values else None,
            "not_all_pair_price_movement": True}


def evaluate(artifacts, records, coverage, model, provenance, baseline):
    """基準を照合し、校正候補を開発で固定してから評価と会計を保存する。"""
    old = {r["race_key"]: r for r in baseline["race_metrics"]}
    reproduced = 0
    for r in records:
        r["r1_probability"] = residual.predict(model, r)
        require(np.isfinite(r["r1_probability"]).all() and np.isclose(r["r1_probability"].sum(), 1), "r1_baseline_invalid_probability")
        if r["race_key"] in old:
            reference = old[r["race_key"]]
            loss = float(-r["target"] @ np.log(np.maximum(r["r1_probability"], 1e-15)))
            require(abs(loss - reference["loss"]["R1"]) < 1e-12, "r1_reference_loss_changed")
            chosen = select_pair(r["r1_probability"], r["prices"], np.ones(len(r["keys"])))
            stake = 600 if chosen is not None else 0
            payout = r["payouts"].get(r["keys"][chosen], 0) * 6 if chosen is not None else 0
            require(stake == reference["stake"]["R1"] and payout == reference["payout"]["R1"], "r1_reference_policy_changed")
            reproduced += 1
    require(reproduced == 1787, "r1_reference_count_changed")
    calibration = [r for r in records if r["period"] == "calibration"]
    development = [r for r in records if r["period"] == "evaluation_2025"]
    train = [r for r in records if r["period"] == "train"]
    require((len(train), len(calibration), len(development)) == (3505, 220, 485), "r1_fit_cohort_changed")
    models = {v: fit_calibrator(calibration, v) for v in VARIANTS}
    price_model = fit_price_model(train)
    losses = {v: float(np.mean([-r["target"] @ np.log(np.maximum(calibrated(r, models[v]), 1e-15)) for r in development])) for v in VARIANTS}
    best = min(losses.values())
    selected = next(v for v in VARIANTS if losses[v] <= best + 1e-12)
    selection = {"selected": selected, "development_losses": losses, "criterion": "development_logloss_then_id_tolerance_1e-12",
                 "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "roi_not_used_for_selection": True}
    payload = {"calibrators": models, "price_model": price_model, "selection": selection, "config": CONFIG, "base_model": provenance}
    artifacts.write_json("metrics.json", {"stage": "selection_frozen", "selection": selection})
    joblib.dump(payload, artifacts.path / "models.joblib")
    saved = joblib.load(artifacts.path / "models.joblib")
    require(digest(saved) == digest(payload), "r1_calibrator_reload_mismatch")
    rows, tickets, diagnostics = [], defaultdict(list), []
    reload_checks = 0

    def predictions():
        """各競走の校正統計と会計を保持し、選択ペアだけをストリーム保存する。"""
        nonlocal reload_checks
        for r in records:
            if r["period"] == "train":
                continue
            row = {"race_key": r["race_key"], "race_date": r["race_date"], "period": r["period"],
                   "loss": {"M0": float(-r["target"] @ np.log(r["market"]))}, "brier": {}, "stake": {}, "payout": {}}
            diagnostic = {"period": r["period"], "variants": {}}
            for v in VARIANTS:
                p = calibrated(r, models[v])
                require(np.array_equal(p, calibrated(r, saved["calibrators"][v])) and np.isclose(p.sum(), 1), "r1_calibration_saved_score_mismatch")
                require(np.array_equal(p, calibrated({**r, "target": np.zeros(len(p)), "payouts": {}}, models[v])), "r1_calibration_result_leak")
                reload_checks += 1
                row["loss"][v] = float(-r["target"] @ np.log(np.maximum(p, 1e-15)))
                row["brier"][v] = float(np.mean((p - r["target"]) ** 2))
                pool = np.flatnonzero((r["prices"] >= 4) & (r["prices"] <= 80) & (p >= .015))
                diagnostic["variants"][v] = {"all_pairs": reliability(p, r["target"]), "candidate_pool": reliability(p, r["target"], pool)}
                for policy in POLICIES:
                    key = v + "_" + policy
                    factors = np.ones(len(p)) if policy == "P0" else discounts(r["prices"], price_model)
                    chosen = select_pair(p, r["prices"], factors)
                    row["loss"][key] = row["loss"][v]
                    row["stake"][key] = row["payout"][key] = 0
                    if chosen is None:
                        continue
                    pair, price = r["keys"][chosen], float(r["prices"][chosen])
                    ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": r["payouts"].get(pair, 0) * 6,
                              "quoted_odds": price, "price_factor": float(factors[chosen]),
                              "expected_multiplier": float(p[chosen] * price * factors[chosen])}
                    row["stake"][key], row["payout"][key] = ticket["stake_yen"], ticket["payout_yen"]
                    tickets[key].append({**ticket, "race_key": r["race_key"], "race_date": r["race_date"], "period": r["period"],
                                         "probability": float(p[chosen]), "target": int(r["target"][chosen])})
                    yield {"race_key": r["race_key"], "race_date": r["race_date"], "venue": r["venue"], "variant": key,
                           "split": r["period"], "horses": list(pair), "probability": float(p[chosen]), "target": int(r["target"][chosen]), "ticket": ticket}
            rows.append(row)
            diagnostics.append(diagnostic)

    predictions_hash = artifacts.write_predictions(predictions())
    probability_results, policy_results, reliability_results = {}, {}, {}
    for v in VARIANTS:
        probability_results[v], reliability_results[v] = {}, {}
        for period in PERIODS:
            subset = [r for r in rows if in_period(r, period)]
            probability_results[v][period] = {"races": len(subset), "logloss": float(np.mean([r["loss"][v] for r in subset])) if subset else None,
                                               "mean_pair_brier": float(np.mean([r["brier"][v] for r in subset])) if subset else None,
                                               **paired_interval(subset, v)}
            groups = [d for d in diagnostics if in_period(d, period)]
            reliability_results[v][period] = {kind: aggregate_reliability([d["variants"][v][kind] for d in groups]) for kind in ("all_pairs", "candidate_pool")}
        for policy in POLICIES:
            key = v + "_" + policy
            policy_results[key] = {}
            for period in PERIODS:
                subset = [r for r in rows if in_period(r, period)]
                chosen = [t for t in tickets[key] if in_period(t, period)]
                account = prior.summary(chosen)
                require(account["stake_yen"] == sum(r["stake"][key] for r in subset)
                        and account["payout_yen"] == sum(r["payout"][key] for r in subset), "r1_calibration_accounting_mismatch")
                policy_results[key][period] = {**account, "hits": sum(t["target"] for t in chosen),
                    "expected_hits": sum(t["probability"] for t in chosen), "evaluation_races": len(subset),
                    "quoted_hit_payout_yen": sum(t["quoted_odds"] * 600 for t in chosen if t["target"]),
                    "uncertainty": residual.bootstrap(subset, key) if subset else None}
    for period, result in policy_results["C0_P0"].items():
        if period == "later_2026":
            continue
        for field in ("races", "stake_yen", "payout_yen", "return_rate"):
            require(result[field] == baseline["results"]["R1"][period][field], "r1_calibration_baseline_summary_changed")
    metrics = {"status": "passed", "stage": "r1_calibration_price", "selection": selection, "calibrators": models,
               "price_model": price_model, "probability_results": probability_results, "policy_results": policy_results,
               "reliability": reliability_results,
               "price_diagnostics": {p: price_diagnostic([r for r in records if in_period(r, p)], p) for p in PERIODS},
               "race_metrics": rows, "coverage": coverage, "base_model": provenance,
               "reference_races_reproduced": reproduced, "reload_score_checks": reload_checks,
               "model_sha256": hashlib.sha256((artifacts.path / "models.joblib").read_bytes()).hexdigest(),
               "base_model_refits": 0, "calibrator_fits": 2, "price_model_fits": 1, "live_adopted": False,
               "default_changed": False, "unseen_test": False, "sqlite_used": False}
    artifacts.write_json("metrics.json", metrics)
    artifacts.finish(overall_complete=False, stage=metrics["stage"], predictions_sha256=predictions_hash,
                     metrics_sha256=digest(metrics), model_sha256=metrics["model_sha256"])
    return {"run_id": artifacts.run_id, "selected": selected, "calibrators": models, "price_model": price_model,
            "probability_2026": {v: probability_results[v]["reused_2026"] for v in VARIANTS},
            "probability_later": {v: probability_results[v]["later_2026"] for v in VARIANTS},
            "policy_2026": {k: v["reused_2026"] for k, v in policy_results.items()},
            "policy_later": {k: v["later_2026"] for k, v in policy_results.items()}}


def execute():
    """専用ガードを設置して固定研究を実行し、失敗時は非秘密証跡を残す。"""
    base.install_input_guard()
    model, provenance = load_model()
    baseline = read_json(existing_run(BASELINE) / "metrics.json")
    artifacts = RunArtifacts({**CONFIG, "base_model": provenance}, "r1-calibration-price")
    artifacts.manifest["code_sha256"]["scripts/run_jra_r1_calibration.py"] = hashlib.sha256((ROOT / "scripts/run_jra_r1_calibration.py").read_bytes()).hexdigest()
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        with threadpool_limits(limits=1):
            records, coverage = prepare(artifacts, baseline)
            return evaluate(artifacts, records, coverage, model, provenance, baseline)
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("r1_calibration_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
