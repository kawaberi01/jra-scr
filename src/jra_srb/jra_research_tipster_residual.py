"""概要: 2003年以降の履歴から馬連市場の残差を直接学習する固定比較。
作成日: 2026-10-17
入力: spec150、統合SQL年別RA/SEと市場snapshot31、spec140の評価集合。
出力: 新規研究runのモデル・選択ペア・診断・会計・入力証跡。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_residual.py
注意事項: SELECT専用。旧SQLite入力・取得・移行・削除・運用変更なし。
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import hashlib
from itertools import combinations
import json
from pathlib import Path
import traceback

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts
from .jra_research_contracts import ResearchError, digest
from .jra_research_history import HistoryConfig
from .jra_research_resources import check_memory
from . import jra_research_tipster_twenty as native
from . import jra_research_tipster_experiment as prior
from . import jra_research_tipster_smoke as base

REFERENCE = "20261017T101337Z_24a898f583fd464093472afb87a88f28"
VARIANTS = ("M0", "M1", "R1", "R2", "R3")
BASIC = [0, 1, 2, 3, 25, 26, 27, 46]
CONTENT = sorted(set(BASIC + [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 28, 29, 30, 37, 38, 39, 43, 44, 45, 47]))
INTERACT = [5, 6, 7, 9, 14, 15, 16, 17, 18, 22]
CONFIG = {"protocol": "spec150-market-residual-pair-v1", "reference": REFERENCE,
          "history_from": "2003-01-01", "train": ["2024-01-01", "2025-09-30"],
          "diagnostic_calibration": ["2025-10-01", "2025-10-31"],
          "development": ["2025-11-01", "2025-12-31"], "reused_evaluation": ["2026-01-01", "2026-05-31"],
          "exclude_months": [6, 7, 8], "variants": list(VARIANTS), "penalty": .1,
          "maxiter": 400, "basic_indices": BASIC, "content_indices": CONTENT,
          "interact_indices": INTERACT, "stake_yen": 600, "odds_band": [4, 80],
          "min_probability": .015, "min_expected_multiplier": 1.05,
          "unseen_test": False, "live_adopted": False}


def load_json(path):
    """UTF-8の保存研究JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def public_features(states, race):
    """当日結果を参照せず、馬IDの前日までの履歴から特徴を作る。"""
    density = sum(bool((h := states.horses.get(r["horse_id"])) and h.last and h.last[-1][3] is not None and h.last[-1][3] <= .3) for r in race["runners"]) / len(race["runners"])
    public = [{k: r[k] for k in ("horse_id", "horse_no", "frame", "age", "weight", "jockey", "trainer")} for r in race["runners"]]
    values = np.asarray([states.vector(r, race, density) for r in public])
    changed = states.vector({**public[0], "rank": 999, "closing": 99, "corner": 99}, race, density)
    if not np.array_equal(values[0], changed):
        raise ResearchError("residual_result_feature_leak", 5)
    return values


def prepare(artifacts, reference):
    """SQL内の必要日を選び、長期履歴と既存市場を同定してメモリに構築する。

    Args:
        artifacts: 今回だけの保存先。原文や全特徴は書き込まない。
        reference: spec140の入力digestと固定評価集合を含む集計。
    Returns:
        tuple: 市場・結果・前日履歴の同定済競走と、年別digest等の監査情報。
    Raises:
        ResearchError: 入力digest、馬ID、評価集合、期間等の契約違反。
    Notes:
        全年の原文は保存しない。同日結果はその日の全特徴作成後に更新する。
    """
    expected = {r["race_key"] for r in reference["race_metrics"]}
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with prior.ExperimentMarketReader(config) as reader:
        rows = reader._small("residual:available_days", "SELECT DISTINCT race_date FROM history.races WHERE __migration_source_snapshot_id=? AND race_date>=? AND race_date<=? ORDER BY race_date", (31, "2024-01-01", "2026-05-31"))
    days = [r["race_date"] for r in rows if prior.split(r["race_date"]) is not None]
    if not days or len(days) > 400:
        raise ResearchError("residual_day_scope", 4)
    states, target, years = native.States(), {}, {}
    checks = 0
    with native.AnnualReader(config) as reader:
        artifacts.write_json("preflight.json", reader.preflight())
        for year in range(2003, 2027):
            raw, audit = reader.year(year)
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
                    if day not in days:
                        continue
                    period = prior.split(day)
                    if period in ("evaluation_2025", "evaluation_early", "evaluation_late") and race["key"] not in expected:
                        continue
                    target[race["key"]] = {"x": public_features(states, race), "runners": race["runners"]}
                    checks += 1
                for race in races:
                    states.update(race)
            years[str(year)] = audit
            artifacts.write_json("coverage.json", {"stage": "native_history", "years": years, "feature_checks": checks})
            print(json.dumps({"stage": "native_history", "year": year, "features_created": checks}), flush=True)
            del grouped
            gc.collect()
            check_memory(2147483648)
    annual_digest = digest({y: value["input_digest"] for y, value in years.items()})
    if annual_digest != reference["coverage"]["input_digest"]:
        raise ResearchError("residual_annual_input_changed", 4)
    del states
    records, excluded, batch_digests = [], [], []
    empty = base.history._build_history_states([])
    with prior.ExperimentMarketReader(config) as reader:
        for offset in range(0, len(days), 4):
            races, rowsets = reader.selected(days[offset:offset + 4])
            converted, missing = base.sql_races(races, rowsets, [], state_provider=lambda _: empty)
            excluded.extend(missing)
            identities = {(r["race_key"], r["horse_no"]): r["horse_id"] for r in rowsets["history.entries"]}
            batch_digests.append(reader.report["input_digest"])
            for data in converted:
                key, day = data["race_id"], data["race_date"]
                period = prior.split(day)
                if period in ("evaluation_2025", "evaluation_early", "evaluation_late") and key not in expected:
                    continue
                entry = target.get(key)
                if entry is None:
                    excluded.append({"race_key": key, "reason": "native_missing"})
                    continue
                runners, rank = entry["runners"], data["result"]["ranks_by_horse"]
                if set(rank) != {r["horse_no"] for r in runners} or any(rank[r["horse_no"]] != r["rank"] or identities.get((key, r["horse_no"])) != r["horse_id"] for r in runners):
                    excluded.append({"race_key": key, "reason": "native_market_mismatch"})
                    continue
                pairs = list(combinations([r["horse_no"] for r in runners], 2))
                prices_map = {tuple(sorted((r["horse_no_1"], r["horse_no_2"]), key=int)): r["odds"] for r in data["inputs"]["odds"]["T-30m"]["quinella"]["pairs"]}
                prices = np.asarray([prices_map[p] for p in pairs])
                market = 1 / prices; market /= market.sum()
                payouts = {tuple(sorted((r["horse_no_1"], r["horse_no_2"]), key=int)): r["payout"] for r in data["result"]["quinella_payout_per_100_yen"]}
                label = np.asarray([float(p in payouts) for p in pairs])
                if label.sum() != 1:
                    excluded.append({"race_key": key, "reason": "non_unique_target"})
                    continue
                records.append({"race_key": key, "race_date": day, "period": period, "venue": data["race"]["course"],
                                "x": entry["x"], "keys": pairs, "prices": prices, "market": market, "target": label, "payouts": payouts})
            print(json.dumps({"stage": "market", "days_read": min(offset + 4, len(days)), "days_total": len(days), "adopted": len(records)}), flush=True)
    common = {r["race_key"] for r in records if r["period"] in ("evaluation_2025", "evaluation_early", "evaluation_late")}
    if common != expected:
        raise ResearchError("residual_reference_cohort_changed", 4, expected=len(expected), actual=len(common))
    coverage = {"years": years, "input_digest": annual_digest, "market_digest": digest(batch_digests),
                "feature_checks": checks, "available_days": days, "adopted_by_split": dict(Counter(r["period"] for r in records)),
                "common_reference_races": len(common), "excluded": excluded, "sqlite_used": False}
    if any(coverage["adopted_by_split"].get(p, 0) == 0 for p in ("train", "calibration", "evaluation_2025", "evaluation_early", "evaluation_late")):
        raise ResearchError("residual_empty_split", 4)
    artifacts.write_json("coverage.json", coverage)
    return sorted(records, key=lambda r: (r["race_date"], r["race_key"])), coverage


def features(record, variant):
    """馬番順に依存しない馬連の和・差と、事前固定の交互作用を返す。

    Args:
        record: 前日までの馬別特徴と現在の市場確率を持つ競走。
        variant: M0/M1/R1/R2/R3の固定方式ID。
    Returns:
        ndarray: 馬連候補を行とする、市場確率で中心化した特徴行列。
    Raises:
        ResearchError: 非有限値を検出した場合。
    """
    logq = np.log(record["market"])
    logq -= record["market"] @ logq
    if variant == "M0":
        return np.empty((len(logq), 0))
    if variant == "M1":
        return logq[:, None]
    indices = BASIC if variant == "R1" else CONTENT
    x = record["x"]
    pairs = np.asarray(list(combinations(range(len(x)), 2)))
    a, b = x[pairs[:, 0]], x[pairs[:, 1]]
    combined = [(a[:, indices] + b[:, indices]) / 2, np.abs(a[:, indices] - b[:, indices])]
    if variant == "R3":
        combined.extend([((a[:, INTERACT] + b[:, INTERACT]) / 2) * logq[:, None],
                         (a[:, 15] * a[:, 16] + b[:, 15] * b[:, 16])[:, None] / 2,
                         (a[:, 9] * a[:, 7] + b[:, 9] * b[:, 7])[:, None] / 2])
    result = np.column_stack((logq, *combined))
    result -= record["market"] @ result
    if not np.isfinite(result).all():
        raise ResearchError("residual_nonfinite_features", 5)
    return result


def fit(records, variant):
    """既存V91の条件付き市場offset尤度で、学習期間だけから補正係数を求める。

    Args:
        records: 2025年9月までの競走のみ。
        variant: spec150で固定した特徴方式。
    Returns:
        dict: 学習だけで求めたスケール、係数、最適化証跡。
    Raises:
        ResearchError: 期間違反または最適化の未収束。
    """
    if any(not CONFIG["train"][0] <= r["race_date"] <= CONFIG["train"][1] for r in records):
        raise ResearchError("residual_training_date_violation", 5)
    artifact = {"variant": variant, "train_races": len(records), "trained_through": max(r["race_date"] for r in records)}
    if variant == "M0":
        return {**artifact, "scale": np.asarray([]), "coef": np.asarray([]), "optimizer": {"success": True, "iterations": 0}}
    x = np.concatenate([features(r, variant) for r in records])
    scale = np.maximum(np.std(x, axis=0), 1e-5)
    x /= scale
    starts = np.cumsum([0] + [len(r["keys"]) for r in records[:-1]])
    group = np.repeat(np.arange(len(records)), [len(r["keys"]) for r in records])
    offset = np.log(np.concatenate([r["market"] for r in records]))
    y = np.concatenate([r["target"] for r in records])

    def objective(beta):
        """競走平均の正則化負対数尤度と解析勾配を返す。"""
        z = offset + x @ beta
        maxima = np.maximum.reduceat(z, starts)
        e = np.exp(z - maxima[group])
        sums = np.add.reduceat(e, starts)
        q = e / sums[group]
        loss = ((maxima + np.log(sums)).sum() - y @ z) / len(records)
        return loss + CONFIG["penalty"] * (beta @ beta) / 2, x.T @ (q - y) / len(records) + CONFIG["penalty"] * beta

    result = minimize(objective, np.zeros(x.shape[1]), jac=True, method="L-BFGS-B", options={"maxiter": CONFIG["maxiter"], "ftol": 1e-11, "gtol": 1e-7})
    if not result.success:
        raise ResearchError("residual_optimizer_failed", 5, variant=variant, status=int(result.status))
    return {**artifact, "scale": scale, "coef": result.x, "optimizer": {"success": True, "iterations": int(result.nit), "objective": float(result.fun)}}


def predict(artifact, record):
    """結果・払戻を使わず、市場と前日履歴だけから馬連確率を返す。"""
    if artifact["variant"] == "M0":
        return record["market"].copy()
    return softmax(np.log(record["market"]) + (features(record, artifact["variant"]) / artifact["scale"]) @ artifact["coef"])


def bootstrap(rows, name):
    """同じ開催日をまとめて再標本化し、市場との損失差とROIの区間を返す。

    Args:
        rows: 同一評価期間の競走別損失・購入額・払戻額。
        name: 比較する固定方式ID。
    Returns:
        dict: 日単位2,000回の探索的95%区間と市場との差。
    Notes:
        既参照期間の診断であり、選択や多重比較の補正はしない。
        購入0のROI区間は内部便宜上0だが、回収率自体は未定義。
    """
    daily = defaultdict(lambda: np.zeros(4))
    for row in rows:
        daily[row["race_date"]] += [row["loss"][name] - row["loss"]["M0"], 1, row["stake"][name], row["payout"][name]]
    values = np.asarray([v for _, v in sorted(daily.items())])
    draw = np.random.default_rng(150).integers(0, len(values), size=(2000, len(values)))
    summed = values[draw].sum(axis=1)
    ratios = summed[:, 3] / np.maximum(summed[:, 2], 1)
    return {"days": len(values), "loss_difference_vs_market": float(values[:, 0].sum() / values[:, 1].sum()),
            "loss_difference_95": np.quantile(summed[:, 0] / summed[:, 1], [.025, .975]).tolist(),
            "roi_95": np.quantile(ratios, [.025, .975]).tolist(), "replicates": 2000,
            "selection_and_multiple_comparisons_not_adjusted": True}


def evaluate(artifacts, records, coverage):
    """学習・開発選択を固定し、保存後再現と共通期間の収益を比較する。

    Args:
        artifacts: 上書きしない新規runの保存先。
        records: 学習・診断・開発・再使用評価へ分割済みの競走。
        coverage: SQL入力digest、件数、除外理由等の監査情報。
    Returns:
        dict: run識別子、開発選択、2026年集計と事前成功基準の判定。
    Raises:
        ResearchError: 最適化、保存後推論、確率、結果非依存に不整合。
    Notes:
        モデルと選択ペアを保存する。購入政策は評価後に変更しない。
    """
    train = [r for r in records if r["period"] == "train"]
    development = [r for r in records if r["period"] == "evaluation_2025"]
    models, dev = {}, {}
    for name in VARIANTS:
        models[name] = fit(train, name)
        dev[name] = float(np.mean([-r["target"] @ np.log(np.maximum(predict(models[name], r), 1e-15)) for r in development]))
        print(json.dumps({"stage": "fit", "variant": name, "development_loss": dev[name], "iterations": models[name]["optimizer"]["iterations"]}), flush=True)
    selected = min(VARIANTS, key=lambda k: (dev[k], k))
    selection = {"selected": selected, "criterion": "development_logloss_then_id", "development_losses": dev,
                 "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "not_unseen_test": True}
    artifacts.write_json("metrics.json", {"stage": "selection_frozen", "selection": selection})
    path = artifacts.path / "models.joblib"
    joblib.dump({"models": models, "config": CONFIG, "selection": selection, "feature_names": native.FEATURES}, path)
    saved = joblib.load(path)["models"]
    rows, tickets = [], defaultdict(list)
    reload_checks = 0

    def predictions():
        """全評価競走の損失を記録し、購入条件を満たす選択ペアだけ保存する。"""
        nonlocal reload_checks
        for record in records:
            if record["period"] == "train":
                continue
            row = {"race_key": record["race_key"], "race_date": record["race_date"], "period": record["period"], "loss": {}, "stake": {}, "payout": {}}
            for name in VARIANTS:
                q = predict(models[name], record)
                if not np.array_equal(q, predict(saved[name], record)) or not np.isclose(q.sum(), 1) or not np.isfinite(q).all():
                    raise ResearchError("residual_saved_prediction_changed", 5)
                changed = {**record, "target": np.zeros_like(record["target"]), "payouts": {}}
                if not np.array_equal(q, predict(models[name], changed)):
                    raise ResearchError("residual_prediction_result_leak", 5)
                reload_checks += 1
                row["loss"][name] = float(-record["target"] @ np.log(np.maximum(q, 1e-15)))
                row["stake"][name] = row["payout"][name] = 0
                ev = q * record["prices"]
                valid = np.flatnonzero((record["prices"] >= 4) & (record["prices"] <= 80) & (q >= .015) & (ev >= 1.05))
                chosen = sorted(valid, key=lambda i: (-round(float(ev[i]), 12), int(i)))[:1]
                for i in chosen:
                    pair = record["keys"][i]
                    ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": record["payouts"].get(pair, 0) * 6,
                              "quoted_odds": float(record["prices"][i]), "expected_multiplier": float(ev[i])}
                    row["stake"][name], row["payout"][name] = ticket["stake_yen"], ticket["payout_yen"]
                    tickets[name].append({**ticket, "race_key": record["race_key"], "race_date": record["race_date"], "period": record["period"]})
                    yield {"race_key": record["race_key"], "race_date": record["race_date"], "venue": record["venue"], "variant": name,
                           "split": record["period"], "horses": list(pair), "probability": float(q[i]), "target": int(record["target"][i]), "ticket": ticket}
            rows.append(row)
    predictions_hash = artifacts.write_predictions(predictions())
    results = {}
    for name in VARIANTS:
        results[name] = {}
        for period in ("calibration", "evaluation_2025", "evaluation_early", "evaluation_late", "reused_2026"):
            def included(row):
                """指定の暦期間に属する競走かを判定する。"""
                return row["period"] == period or period == "reused_2026" and row["period"] in ("evaluation_early", "evaluation_late")
            subset = [r for r in rows if included(r)]
            summary = prior.summary([t for t in tickets[name] if included(t)])
            results[name][period] = {**summary, "evaluation_races": len(subset), "logloss": float(np.mean([r["loss"][name] for r in subset])),
                                     "uncertainty": bootstrap(subset, name)}
    selected_result = results[selected]["reused_2026"]
    success = bool((selected_result["return_rate"] or 0) > 1
                   and all((results[selected][p]["return_rate"] or 0) > 1 for p in ("evaluation_early", "evaluation_late"))
                   and selected_result["days"] >= 30 and selected_result["uncertainty"]["roi_95"][0] > 1)
    metrics = {"status": "passed", "stage": "market_residual_content", "coverage": coverage, "selection": selection,
               "results": results, "purchase_success_criteria_met": success, "live_adopted": False, "unseen_test": False,
               "race_metrics": rows, "reload_score_checks": reload_checks, "sqlite_used": False,
               "optimizers": {k: v["optimizer"] for k, v in models.items()},
               "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    artifacts.write_json("metrics.json", metrics)
    artifacts.finish(overall_complete=False, stage=metrics["stage"], predictions_sha256=predictions_hash, metrics_sha256=digest(metrics))
    return {"run_id": artifacts.run_id, "selection": selection, "purchase_success_criteria_met": success,
            "results_2026": {name: results[name]["reused_2026"] for name in VARIANTS}}


def execute_residual():
    """SQLだけの固定研究を実行し、失敗時は秘密を含まない証跡を保存する。

    Returns:
        dict: 新規runの方式選択と固定期間の評価結果。
    Raises:
        ResearchError: 入力・学習・評価の契約に違反した場合。
    Notes:
        専用プロセスへ解除しない入力guardを設置し、SELECTでSQLを読む。
        run内だけへ保存し、原データ・既存成果物・運用は変更しない。
    """
    base.install_input_guard()
    artifacts = RunArtifacts(CONFIG, "tipster-market-residual")
    for name in ("src/jra_srb/jra_research_tipster_residual.py", "scripts/run_jra_tipster_residual.py"):
        artifacts.manifest["code_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        reference = load_json(ROOT / "artifacts/jra_research/runs" / REFERENCE / "metrics.json")
        with threadpool_limits(limits=1):
            records, coverage = prepare(artifacts, reference)
            return evaluate(artifacts, records, coverage)
    except ResearchError as error:
        artifacts.fail(error)
        raise
    except Exception as error:
        frames = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(error.__traceback__)]
        failure = ResearchError("tipster_residual_failed", 4, error_type=type(error).__name__, frames=frames)
        artifacts.fail(failure)
        raise failure from None
