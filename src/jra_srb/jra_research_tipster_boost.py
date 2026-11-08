"""概要: 既存V105の木補正をJV長期履歴・馬連市場へ適用する固定比較。
作成日: 2026-10-17
入力: spec160、spec150の保存モデル、統合SQLの同一入力。
出力: 新規runの木モデル・選択ペア・時系列評価・検証証跡。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_boost.py --baseline-run <run-id>
注意事項: 既存fit_boostを再利用。SQL SELECTのみ、旧データ入力・削除なし。
"""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import traceback

import joblib
import numpy as np
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest
from .jra_research_resources import check_memory
from . import jra_research_tipster_residual as residual
from . import jra_research_tipster_experiment as prior
from . import jra_research_tipster_smoke as base

VARIANTS = ("M0", "R1", "R2", "B1", "B2")


def legacy_algorithm():
    """既存V105実装を読み込み、取得や旧ファイルの読取は実行しない。

    Returns:
        module: fit_boostとboost_deltaを持つ既存研究モジュール。
    Notes:
        既存scriptsのimportに必要な検索パスだけを追加する。
    """
    script_path = str(ROOT / "scripts")
    if script_path not in sys.path:
        sys.path.insert(0, script_path)
    return importlib.import_module("jra_second_ten_model")


def predict(model, record, algorithm):
    """市場と前日履歴に木の補正を加えて馬連確率へ正規化する。"""
    if model["kind"] == "linear":
        return residual.predict(model["artifact"], record)
    data = {"keys": record["keys"], "boost_x": residual.features(record, model["features"])}
    return softmax(np.log(record["market"]) + algorithm.boost_delta(model["artifact"], data))


def evaluate(artifacts, records, coverage, baseline_path, baseline_metrics, algorithm):
    """線形基準を再利用し、新規2木モデルを学習して同じ購入政策で比較する。

    Args:
        artifacts: 新規runの保存先。
        records: SQLから同定済みの期間分割競走。
        coverage: 入力digestと件数等の監査情報。
        baseline_path: 既存の線形モデルを保存したspec150のrun。
        baseline_metrics: 再現を要求する線形モデルの集計値。
        algorithm: 変更せず再利用する既存V105の実装モジュール。
    Returns:
        dict: 開発で固定した選択案と2026年評価の集計。
    Raises:
        ResearchError: 保存後推論、結果非依存、線形基準再現に不整合。
    Notes:
        新規学習はB1/B2だけ。モデル・購入ペアを今回のrunへ保存する。
    """
    old = joblib.load(baseline_path / "models.joblib")["models"]
    models = {name: {"kind": "linear", "artifact": old[name]} for name in ("M0", "R1", "R2")}
    train = [r for r in records if r["period"] == "train"]
    for name, feature in (("B1", "R1"), ("B2", "R2")):
        print(json.dumps({"stage": "boost_fit_start", "variant": name, "training_races": len(train)}), flush=True)
        inputs = [{"keys": r["keys"], "market": r["market"], "target": r["target"], "boost_x": residual.features(r, feature)} for r in train]
        fitted = algorithm.fit_boost(inputs, rounds=100)
        models[name] = {"kind": "boost", "features": feature, "artifact": fitted}
        del inputs
        check_memory(2147483648)
        print(json.dumps({"stage": "boost_fit_finished", "variant": name, "trees": len(fitted["trees"])}), flush=True)
    development = [r for r in records if r["period"] == "evaluation_2025"]
    dev = {name: float(np.mean([-r["target"] @ np.log(np.maximum(predict(model, r, algorithm), 1e-15)) for r in development])) for name, model in models.items()}
    selected = min(VARIANTS, key=lambda k: (dev[k], k))
    selection = {"selected": selected, "development_losses": dev, "criterion": "development_logloss_then_id",
                 "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "not_unseen_test": True}
    artifacts.write_json("metrics.json", {"stage": "selection_frozen", "selection": selection})
    path = artifacts.path / "models.joblib"
    joblib.dump({"models": models, "selection": selection, "config": artifacts_config(baseline_path.name)}, path)
    saved = joblib.load(path)["models"]
    rows, tickets = [], defaultdict(list)
    checks = 0

    def predictions():
        """全競走の損失を保持し、条件を満たす購入だけを成果物へ保存する。"""
        nonlocal checks
        for r in records:
            if r["period"] == "train":
                continue
            row = {"race_key": r["race_key"], "race_date": r["race_date"], "period": r["period"], "loss": {}, "stake": {}, "payout": {}}
            for name in VARIANTS:
                q = predict(models[name], r, algorithm)
                altered = {**r, "target": np.zeros_like(r["target"]), "payouts": {}}
                if not np.array_equal(q, predict(saved[name], r, algorithm)) or not np.array_equal(q, predict(models[name], altered, algorithm)):
                    raise ResearchError("boost_reload_or_result_leak", 5)
                if not np.isfinite(q).all() or not np.isclose(q.sum(), 1):
                    raise ResearchError("boost_invalid_probability", 5)
                checks += 1
                row["loss"][name] = float(-r["target"] @ np.log(np.maximum(q, 1e-15)))
                row["stake"][name] = row["payout"][name] = 0
                ev = q * r["prices"]
                valid = np.flatnonzero((r["prices"] >= 4) & (r["prices"] <= 80) & (q >= .015) & (ev >= 1.05))
                for i in sorted(valid, key=lambda i: (-round(float(ev[i]), 12), int(i)))[:1]:
                    pair = r["keys"][i]
                    ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": r["payouts"].get(pair, 0) * 6,
                              "quoted_odds": float(r["prices"][i]), "expected_multiplier": float(ev[i])}
                    row["stake"][name], row["payout"][name] = ticket["stake_yen"], ticket["payout_yen"]
                    tickets[name].append({**ticket, "race_key": r["race_key"], "race_date": r["race_date"], "period": r["period"]})
                    yield {"race_key": r["race_key"], "race_date": r["race_date"], "venue": r["venue"], "variant": name,
                           "split": r["period"], "horses": list(pair), "probability": float(q[i]), "target": int(r["target"][i]), "ticket": ticket}
            rows.append(row)
    prediction_hash = artifacts.write_predictions(predictions())
    results = {}
    for name in VARIANTS:
        results[name] = {}
        for period in ("calibration", "evaluation_2025", "evaluation_early", "evaluation_late", "reused_2026"):
            def included(row):
                """固定した暦期間の対象かを判定する。"""
                return row["period"] == period or period == "reused_2026" and row["period"] in ("evaluation_early", "evaluation_late")
            subset = [r for r in rows if included(r)]
            results[name][period] = {**prior.summary([t for t in tickets[name] if included(t)]), "evaluation_races": len(subset),
                                     "logloss": float(np.mean([r["loss"][name] for r in subset])), "uncertainty": residual.bootstrap(subset, name)}
    for name in ("M0", "R1", "R2"):
        for period, values in results[name].items():
            previous = baseline_metrics["results"][name][period]
            if any(values[k] != previous[k] for k in ("stake_yen", "payout_yen", "evaluation_races", "logloss")):
                raise ResearchError("boost_linear_reference_changed", 5, variant=name, period=period)
    chosen = results[selected]["reused_2026"]
    success = bool((chosen["return_rate"] or 0) > 1 and chosen["days"] >= 30 and chosen["uncertainty"]["roi_95"][0] > 1
                   and all((results[selected][p]["return_rate"] or 0) > 1 for p in ("evaluation_early", "evaluation_late")))
    metrics = {"status": "passed", "stage": "market_residual_boost", "coverage": coverage, "selection": selection, "results": results,
               "race_metrics": rows, "reload_score_checks": checks, "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "optimizers": {k: {"success": True, "algorithm_completed": True, "not_global_optimum_claim": True} for k in VARIANTS},
               "new_fits": 2, "linear_models_reused": ["M0", "R1", "R2"], "baseline_run": baseline_path.name,
               "purchase_success_criteria_met": success, "live_adopted": False, "unseen_test": False, "sqlite_used": False}
    artifacts.write_json("metrics.json", metrics)
    artifacts.finish(overall_complete=False, stage=metrics["stage"], predictions_sha256=prediction_hash, metrics_sha256=digest(metrics))
    return {"run_id": artifacts.run_id, "selection": selection, "purchase_success_criteria_met": success,
            "results_2026": {k: results[k]["reused_2026"] for k in VARIANTS}}


def artifacts_config(baseline_run):
    """線形比較から変更しない期間・政策と固定した木設定を返す。"""
    return {**residual.CONFIG, "protocol": "spec160-market-residual-boost-v1", "baseline_run": baseline_run,
            "variants": list(VARIANTS), "rounds": 100, "max_leaf_nodes": 6, "min_samples_leaf": 150,
            "learning_rate": .05, "hessian_addition": .02, "target_clip": [-2, 2], "seed_start": 102}


def execute_boost(baseline_run):
    """線形研究の未達を確認して、同じSQL入力から新しい木比較だけを実行する。

    Args:
        baseline_run: 成功基準未達で完了したspec150のrun識別子。
    Returns:
        dict: 新しいrunの選択案と固定期間の集計。
    Raises:
        ResearchError: 基準runの資格・hash・入力一致等に違反した場合。
    Notes:
        専用プロセスで入力guardを設置する。SQLはSELECTだけを実行し、
        旧データや運用を変更せず、失敗証跡も今回のrunへ保存する。
    """
    base.install_input_guard()
    old_path = existing_run(baseline_run)
    old = residual.load_json(old_path / "metrics.json")
    if old["status"] != "passed" or old["purchase_success_criteria_met"]:
        raise ResearchError("boost_baseline_not_eligible", 3)
    if hashlib.sha256((old_path / "models.joblib").read_bytes()).hexdigest() != old["model_sha256"]:
        raise ResearchError("boost_baseline_hash_failed", 3)
    artifacts = RunArtifacts(artifacts_config(baseline_run), "tipster-market-residual-boost")
    for name in ("src/jra_srb/jra_research_tipster_boost.py", "scripts/run_jra_tipster_boost.py", "scripts/jra_second_ten_model.py"):
        artifacts.manifest["code_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        reference = residual.load_json(existing_run(residual.REFERENCE) / "metrics.json")
        with threadpool_limits(limits=1):
            records, coverage = residual.prepare(artifacts, reference)
            for key in ("input_digest", "market_digest", "adopted_by_split"):
                if coverage[key] != old["coverage"][key]:
                    raise ResearchError("boost_source_changed", 5)
            return evaluate(artifacts, records, coverage, old_path, old, legacy_algorithm())
    except ResearchError as error:
        artifacts.fail(error)
        raise
    except Exception as error:
        frames = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(error.__traceback__)]
        failure = ResearchError("tipster_boost_failed", 4, error_type=type(error).__name__, frames=frames)
        artifacts.fail(failure)
        raise failure from None
