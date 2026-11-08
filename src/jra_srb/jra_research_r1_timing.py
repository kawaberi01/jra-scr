"""概要: R1のT10市場更新を、事前固定した継続・終了基準で1案だけ検証する。
作成日: 2026-10-18
入力: spec190、元R1、spec180成果物、統合SQL履歴・T30/T10・HR払戻。
出力: 研究runの判定・比較・保存予測・検証証跡。
実行例: uv run --frozen --extra ml python scripts/run_jra_r1_timing.py
注意事項: 開発基準未達なら後続評価を行わない。再学習・既定変更・外部AI送信なし。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import hashlib
from itertools import combinations
import json

import numpy as np
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest, timestamp
from .jra_research_features import numeric_market
from .jra_research_history import HistoryConfig
from .jra_research_resources import check_memory
from .jra_research_r1_live import LiveAnnualReader, load_model, read_json, require
from .jra_research_r1_calibration import select_pair
from . import jra_research_tipster_twenty as native
from . import jra_research_tipster_residual as residual
from . import jra_research_tipster_experiment as prior
from . import jra_research_tipster_smoke as base


REFERENCE = "20261017T163427Z_79bd6188d33b46c19164600dd57840e8"
VARIANTS = ("M30", "R30", "M10", "R10")
CONFIG = {"protocol": "spec190-r1-timing-stop-rule-v1", "reference_run": REFERENCE,
          "candidate_count": 1, "base_model_refits": 0, "max_adjustment_rounds": 0,
          "min_relative_logloss_gain_vs_r30": .005, "min_relative_logloss_gain_vs_m10": .0025,
          "min_coverage": .95, "max_brier_relative_worsening": .005,
          "development_min_races": 400, "development_min_days": 15,
          "evaluation_min_races": 1000, "evaluation_min_days": 40,
          "bootstrap_replicates": 2000, "paired_comparison_interval": .975,
          "purchase_min_bets": 100, "purchase_min_days": 30, "purchase_min_hits": 10,
          "purchase_min_roi": 1.05, "purchase_min_roi_point_gain": .05,
          "default_changed": False, "unseen_test": False}


def prepare_features(artifacts, reference):
    """元採用競走の履歴だけを時系列再構築し、全年度の入力digestを照合する。"""
    scope = {r["race_key"] for r in reference["race_metrics"] if r["period"] != "calibration"}
    states, targets, years = native.States(), {}, {}
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with LiveAnnualReader(config) as reader:
        artifacts.write_json("preflight.json", reader.preflight())
        for year in range(2003, 2027):
            raw, audit = reader.year_before(year, "2026-10-05") if year == 2026 else reader.year(year)
            require(audit["input_digest"] == reference["coverage"]["years"][str(year)]["input_digest"], "timing_annual_digest_changed")
            grouped = defaultdict(list)
            for key, source in sorted(raw.items()):
                race, reason = native.parse_race(key, source)
                if reason is None:
                    grouped[race["day"]].append(race)
            del raw
            for day, races in sorted(grouped.items()):
                for race in races:
                    if race["key"] in scope:
                        targets[race["key"]] = {"x": residual.public_features(states, race), "race": race}
                for race in races:
                    states.update(race)
            years[str(year)] = {"input_digest": audit["input_digest"]}
            artifacts.write_json("coverage.json", {"stage": "history", "years": years, "features_created": len(targets)})
            if year % 4 == 3 or year >= 2024:
                print(json.dumps({"stage": "history", "year": year, "features_created": len(targets)}), flush=True)
            del grouped
            gc.collect()
            check_memory(2147483648)
    require(set(targets) == scope and len(targets) == 1764, "timing_feature_cohort_changed")
    return targets, years


def indexed_rows(reader, keys, table, fields, extra):
    """検査済みの固定表へ、版と元値付きrace hashで100競走以内を照会する。"""
    require(table in {"market.odds_asof_index", "history.payouts"} and 0 < len(keys) <= 100, "timing_invalid_query_scope")
    clause = ",".join(["(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))"] * len(keys))
    params = [v for key in keys for v in (hashlib.sha256(key.encode("utf-16le")).digest(), key)] + [31]
    sql = "SELECT " + ",".join("t.[" + f + "]" for f in fields)
    # 払戻は100競走のVALUES結合が全走査へ退行したため、既存の版+race hash索引を明示する。
    route = " WITH (INDEX(IX_unified_race), FORCESEEK)" if table == "history.payouts" else ""
    sql += " FROM " + table + " t" + route + " JOIN (VALUES " + clause + ") k(hash_value,race_key) ON t.__unified_race_sha256=k.hash_value AND CONVERT(varbinary(max),t.race_key)=CONVERT(varbinary(max),k.race_key) WHERE t.__migration_source_snapshot_id=? " + extra
    rows = reader._small("timing:" + table, sql, params)
    require(all(r["race_key"] in keys for r in rows), "timing_race_hash_mismatch")
    return rows


def two_markets(rows, pairs):
    """同じ有効ペア集合のT30/T10と公表時刻の整合を検査する。"""
    require(len(rows) == 2 and {r["horizon"] for r in rows} == {"T30", "T10"}, "timing_missing_horizon")
    values = {r["horizon"]: r for r in rows}
    for r in rows:
        require(r["selection_status"] == "selected" and r["parser_version"] == "jv-o1o2-v2" and r["content_sha256"]
                and timestamp(r["announced_at"]) <= timestamp(r["cutoff_at"]), "timing_invalid_market")
    require((timestamp(values["T10"]["cutoff_at"]) - timestamp(values["T30"]["cutoff_at"])).total_seconds() == 1200, "timing_cutoff_mismatch")
    prices = {h: numeric_market(values[h], "quinella") for h in ("T30", "T10")}
    require(all(set(p) == set(pairs) for p in prices.values()), "timing_roster_mismatch")
    return {h: np.asarray([p[key] for key in pairs]) for h, p in prices.items()}


def score_market(model, x, prices):
    """その時点の市場を更新してR1を再推論し、独立式と結果非依存を照合する。"""
    market = 1 / prices
    market /= market.sum()
    record = {"x": x, "market": market}
    probabilities = residual.predict(model, record)
    pair_x = x[:, residual.BASIC]
    combinations_x = list(combinations(range(len(x)), 2))
    logq = np.log(market)
    centered = logq - market @ logq
    z = []
    for index, (i, j) in enumerate(combinations_x):
        row = np.asarray([centered[index], *((pair_x[i] + pair_x[j]) / 2), *np.abs(pair_x[i] - pair_x[j])])
        z.append(logq[index] + (row / model["scale"]) @ model["coef"])
    independent = np.exp(np.asarray(z) - max(z))
    independent /= independent.sum()
    require(np.allclose(probabilities, independent, rtol=1e-12, atol=1e-14) and np.isfinite(probabilities).all()
            and np.isclose(probabilities.sum(), 1), "timing_independent_score_mismatch")
    require(np.array_equal(probabilities, residual.predict(model, {**record, "target": 999, "payouts": {"fake": 999}})), "timing_result_dependency")
    return market, probabilities


def paired_metrics(rows, reference):
    """同一開催日で候補と基準の損失差・改善率を再標本化する。"""
    if not rows:
        return {"reference_loss": None, "candidate_loss": None, "relative_gain": None, "difference_95": None, "difference_adjusted": None}
    daily = defaultdict(lambda: np.zeros(3))
    for r in rows:
        daily[r["race_date"]] += [r["loss"]["R10"], r["loss"][reference], 1]
    values = np.asarray([v for _, v in sorted(daily.items())])
    candidate, baseline = values[:, :2].sum(axis=0) / len(rows)
    draws = np.random.default_rng(190).integers(0, len(values), size=(2000, len(values)))
    sums = values[draws].sum(axis=1)
    differences = (sums[:, 0] - sums[:, 1]) / sums[:, 2]
    return {"reference_loss": float(baseline), "candidate_loss": float(candidate),
            "relative_gain": float((baseline - candidate) / baseline),
            "difference_95": np.quantile(differences, [.025, .975]).tolist(),
            "difference_adjusted": np.quantile(differences, [.0125, .9875]).tolist()}


def accuracy_gate(rows, expected, stage):
    """実行前固定の最小改善幅・区間・標本・Brier条件を機械判定する。"""
    r30, m10 = paired_metrics(rows, "R30"), paired_metrics(rows, "M10")
    days = len({r["race_date"] for r in rows})
    minimum_races = CONFIG["development_min_races"] if stage == "development" else CONFIG["evaluation_min_races"]
    minimum_days = CONFIG["development_min_days"] if stage == "development" else CONFIG["evaluation_min_days"]
    brier = {v: float(np.mean([r["brier"][v] for r in rows])) if rows else None for v in VARIANTS}
    checks = {"coverage": expected > 0 and len(rows) / expected >= .95, "minimum_races": len(rows) >= minimum_races,
              "minimum_days": days >= minimum_days,
              "relative_gain_vs_r30": r30["relative_gain"] is not None and r30["relative_gain"] >= .005,
              "relative_gain_vs_m10": m10["relative_gain"] is not None and m10["relative_gain"] >= .0025,
              "adjusted_interval_vs_r30": r30["difference_adjusted"] is not None and r30["difference_adjusted"][1] < 0,
              "adjusted_interval_vs_m10": m10["difference_adjusted"] is not None and m10["difference_adjusted"][1] < 0,
              "brier_vs_r30": bool(rows) and brier["R10"] <= brier["R30"] * 1.005,
              "brier_vs_m10": bool(rows) and brier["R10"] <= brier["M10"] * 1.005}
    return {"stage": stage, "passed": all(checks.values()), "checks": checks, "races": len(rows), "expected_races": expected,
            "days": days, "vs_r30": r30, "vs_m10": m10, "brier": brier}


def evaluate_phase(keys, targets, reference, model, reader, tickets):
    """指定期間だけ市場とHRを取得し、T30基準を再現して4方式を同じ競走で比較する。"""
    rows, excluded = [], []
    old = {r["race_key"]: r for r in reference["race_metrics"]}
    for offset in range(0, len(keys), 100):
        batch = keys[offset:offset + 100]
        markets = indexed_rows(reader, batch, "market.odds_asof_index", base.FIELDS["market.odds_asof_index"],
                               "AND t.market=N'quinella' AND t.horizon IN (N'T30',N'T10')")
        payouts = indexed_rows(reader, batch, "history.payouts", base.FIELDS["history.payouts"],
                               "AND t.market=N'quinella' AND t.slot_status=N'published'")
        by_market, by_payout = defaultdict(list), defaultdict(list)
        for r in markets:
            by_market[r["race_key"]].append(r)
        for r in payouts:
            by_payout[r["race_key"]].append(r)
        for key in batch:
            source = targets[key]
            race = source["race"]
            pairs = list(combinations([r["horse_no"] for r in race["runners"]], 2))
            try:
                prices = two_markets(by_market[key], pairs)
            except ResearchError as error:
                excluded.append({"race_key": key, "reason": error.reason})
                continue
            winners = tuple(sorted((r["horse_no"] for r in race["runners"] if r["rank"] <= 2)))
            hr = by_payout[key]
            require(len(hr) == 1 and hr[0]["hr_sha256"] and hr[0]["payout_yen"] > 0
                    and int(hr[0]["payout_raw"]) == hr[0]["payout_yen"]
                    and hr[0]["selection_raw"] == "".join(winners), "timing_payout_contract")
            actual = hr[0]["payout_yen"]
            y = np.asarray([float(p == winners) for p in pairs])
            require(y.sum() == 1, "timing_nonunique_target")
            row = {"race_key": key, "race_date": race["day"], "period": old[key]["period"],
                   "loss": {}, "brier": {}, "stake": {}, "payout": {}}
            for horizon in ("T30", "T10"):
                market, probabilities = score_market(model, source["x"], prices[horizon])
                for variant, p in (("M" + horizon[1:], market), ("R" + horizon[1:], probabilities)):
                    row["loss"][variant] = float(-y @ np.log(np.maximum(p, 1e-15)))
                    row["brier"][variant] = float(np.mean((p - y) ** 2))
                    index = select_pair(p, prices[horizon], np.ones(len(p)))
                    row["stake"][variant] = row["payout"][variant] = 0
                    if index is not None:
                        pair = pairs[index]
                        ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": actual * 6 if pair == winners else 0,
                                  "quoted_odds": float(prices[horizon][index]), "expected_multiplier": float(p[index] * prices[horizon][index])}
                        row["stake"][variant], row["payout"][variant] = ticket["stake_yen"], ticket["payout_yen"]
                        tickets.append({"race_key": key, "race_date": race["day"], "venue": old[key].get("venue", ""),
                                        "variant": variant, "split": row["period"], "horses": list(pair),
                                        "probability": float(p[index]), "target": int(pair == winners), "ticket": ticket})
            require(abs(row["loss"]["R30"] - old[key]["loss"]["C0"]) < 1e-12
                    and row["stake"]["R30"] == old[key]["stake"]["C0_P0"]
                    and row["payout"]["R30"] == old[key]["payout"]["C0_P0"], "timing_r30_reference_changed")
            rows.append(row)
    return rows, excluded


def summaries(rows, tickets):
    """全競走の損失と固定政策の会計を、方式ごとに集計する。"""
    result = {}
    for variant in VARIANTS:
        chosen = [r for r in tickets if r["variant"] == variant]
        accounting = prior.summary([{**r["ticket"], "race_key": r["race_key"], "race_date": r["race_date"]} for r in chosen])
        require(accounting["stake_yen"] == sum(r["stake"][variant] for r in rows)
                and accounting["payout_yen"] == sum(r["payout"][variant] for r in rows), "timing_accounting_mismatch")
        result[variant] = {"logloss": float(np.mean([r["loss"][variant] for r in rows])) if rows else None,
                           "mean_pair_brier": float(np.mean([r["brier"][variant] for r in rows])) if rows else None,
                           **accounting, "hits": sum(r["target"] for r in chosen),
                           "expected_hits": sum(r["probability"] for r in chosen)}
    return result


def purchase_gate(rows, tickets):
    """購入採用の標本数・利益改善を判定し、不足なら条件探索をせず保留する。"""
    report = summaries(rows, tickets)
    candidate, baseline = report["R10"], report["R30"]
    enough = candidate["races"] >= 100 and candidate["days"] >= 30 and candidate["hits"] >= 10
    checks = {"minimum_bets": candidate["races"] >= 100, "minimum_days": candidate["days"] >= 30,
              "minimum_hits": candidate["hits"] >= 10,
              "roi_at_least_105": (candidate["return_rate"] or 0) >= 1.05,
              "roi_gain_5_points": candidate["return_rate"] is not None and baseline["return_rate"] is not None
                  and candidate["return_rate"] - baseline["return_rate"] >= .05}
    intervals = None
    if enough:
        daily = defaultdict(lambda: np.zeros(3))
        for r in rows:
            daily[r["race_date"]] += [r["stake"]["R10"], r["payout"]["R10"],
                (r["payout"]["R10"] - r["stake"]["R10"]) - (r["payout"]["R30"] - r["stake"]["R30"])]
        values = np.asarray([v for _, v in sorted(daily.items())])
        draws = np.random.default_rng(191).integers(0, len(values), size=(2000, len(values)))
        sums = values[draws].sum(axis=1)
        roi = sums[:, 1] / np.maximum(sums[:, 0], 1)
        intervals = {"roi_95": np.quantile(roi, [.025, .975]).tolist(), "profit_delta_95": np.quantile(sums[:, 2], [.025, .975]).tolist()}
    checks["roi_lower_above_100"] = intervals is not None and intervals["roi_95"][0] > 1
    checks["profit_delta_lower_above_zero"] = intervals is not None and intervals["profit_delta_95"][0] > 0
    return {"status": "passed" if all(checks.values()) else "insufficient_sample" if not enough else "failed",
            "checks": checks, "intervals": intervals, "summaries": report}


def execute():
    """T10更新1案を一次判定し、未達なら評価を追加せず系列を終了する。"""
    base.install_input_guard()
    path = existing_run(REFERENCE)
    reference, manifest = read_json(path / "metrics.json"), read_json(path / "manifest.json")
    require(manifest["status"] == "complete" and digest(reference) == manifest["metrics_sha256"], "timing_invalid_reference")
    model, provenance = load_model()
    artifacts = RunArtifacts({**CONFIG, "base_model": provenance}, "r1-timing-stop-rule")
    artifacts.manifest["code_sha256"]["scripts/run_jra_r1_timing.py"] = hashlib.sha256((ROOT / "scripts/run_jra_r1_timing.py").read_bytes()).hexdigest()
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        with threadpool_limits(limits=1):
            targets, years = prepare_features(artifacts, reference)
            old = reference["race_metrics"]
            dev_keys = sorted(r["race_key"] for r in old if r["period"] == "evaluation_2025")
            eval_keys = sorted(r["race_key"] for r in old if r["period"] in ("evaluation_early", "evaluation_late", "later_2026"))
            tickets, evaluation, evaluation_excluded = [], [], []
            config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
            with prior.ExperimentMarketReader(config) as reader:
                reader.selected(["2025-11-01"])
                development, dev_excluded = evaluate_phase(dev_keys, targets, reference, model, reader, tickets)
                screen = accuracy_gate(development, len(dev_keys), "development")
                artifacts.write_json("metrics.json", {"stage": "development_decision_frozen", "development_gate": screen})
                print(json.dumps({"stage": "development_decision", "passed": screen["passed"], "checks": screen["checks"]}), flush=True)
                if screen["passed"]:
                    evaluation, evaluation_excluded = evaluate_phase(eval_keys, targets, reference, model, reader, tickets)
            final = accuracy_gate(evaluation, len(eval_keys), "evaluation") if screen["passed"] else None
            if final is not None:
                non_worse = {p: bool(s := [r for r in evaluation if r["period"] == p])
                    and np.mean([r["loss"]["R10"] for r in s]) <= np.mean([r["loss"]["R30"] for r in s])
                    for p in ("evaluation_early", "evaluation_late", "later_2026")}
                final["checks"].update({"non_worse_" + p: bool(v) for p, v in non_worse.items()})
                final["passed"] = all(final["checks"].values())
            supported = screen["passed"] and final is not None and final["passed"]
            decision = {"accuracy_candidate_supported": bool(supported), "stop_further_tuning": True,
                "research_status": "prospective_validation_only" if supported else "closed_failed_performance_gate",
                "family": "R1_current_input_calibration_price_market_timing", "next_variants_allowed": 0,
                "reason": "passed_retrospective_gate_not_independent_test" if supported else "development_gate_failed" if not screen["passed"] else "evaluation_gate_failed",
                "resumption_requires_new_information_or_new_independent_data_and_explicit_request": True}
            all_rows = development + evaluation
            prediction_hash = artifacts.write_predictions(tickets)
            metrics = {"status": "passed", "stage": "r1_timing_stop_rule", "development_gate": screen, "evaluation_gate": final,
                "decision": decision, "development_results": summaries(development, [t for t in tickets if t["split"] == "evaluation_2025"]),
                "evaluation_results": purchase_gate(evaluation, [t for t in tickets if t["split"] != "evaluation_2025"]) if evaluation else None,
                "race_metrics": all_rows, "base_model": provenance, "new_fits": 0, "default_changed": False,
                "evaluation_executed": bool(screen["passed"]), "unseen_test": False}
            coverage = {"years": years, "features_created": len(targets), "development_expected": len(dev_keys),
                "development_adopted": len(development), "evaluation_expected": len(eval_keys), "evaluation_adopted": len(evaluation),
                "evaluation_market_not_read_when_screen_failed": not screen["passed"],
                "excluded": dev_excluded + evaluation_excluded, "exclusion_counts": dict(Counter(r["reason"] for r in dev_excluded + evaluation_excluded)),
                "reference_cohort": 1764, "sqlite_used": False}
            artifacts.write_json("coverage.json", coverage)
            artifacts.write_json("metrics.json", metrics)
            artifacts.finish(overall_complete=False, metrics_sha256=digest(metrics), predictions_sha256=prediction_hash,
                performance_gate_passed=bool(supported), research_status=decision["research_status"], default_changed=False)
            return {"run_id": artifacts.run_id, "development_gate": screen, "evaluation_gate": final, "decision": decision,
                    "development_results": metrics["development_results"]}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("r1_timing_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
