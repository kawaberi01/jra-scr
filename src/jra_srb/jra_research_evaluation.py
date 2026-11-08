"""概要: SQL研究の時系列学習・確率評価・単勝精算を共通化する。
作成日: 2026-10-15
入力: 結果と分離したInputRace、OutcomeBundle、研究設定。
出力: 契約付き学習モデル、予測、校正・精算指標。
実行例: uv run pytest -q tests/test_jra_research_evaluation.py
注意事項: 学習集合だけでfitし、100円当り公式払戻を金額として扱う。
"""

from __future__ import annotations

from collections import defaultdict
import math
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .jra_research_contracts import (
    CONTRACT_VERSION, FEATURE_NAMES, MASKED_NAMES, PROFILE_ID, InputRace, OutcomeBundle,
    ResearchConfig, ResearchDataset, ResearchError, digest,
)
from .jra_research_resources import check_memory, memory_bytes


def feature_contract(variant: str, build_identity_sha256: str) -> dict:
    """学習/scoreで一致が必要な順序・型・欠損・定義を返す。"""
    if variant not in {"basic", "cross"}:
        raise ResearchError("unsupported_model_variant", 2)
    return {"contract_version": CONTRACT_VERSION, "profile_id": PROFILE_ID, "variant": variant,
            "feature_names": list(FEATURE_NAMES[:8] if variant == "basic" else FEATURE_NAMES),
            "dtype": "float64", "masked_names": sorted(MASKED_NAMES), "missing_policy": "reject_race",
            "probability_policy": "binary_logistic_then_race_normalize_v1",
            "history_identity": "horse_id_O1_roster", "build_identity_sha256": build_identity_sha256}


def train_models(dataset: ResearchDataset, config: ResearchConfig) -> dict[str, dict]:
    """train開催だけでbasic8/cross9の新しいモデルを学習する。"""
    selected = [r for r in dataset.races if config.split(r.race_date) == "train"]
    if not selected:
        raise ResearchError("empty_training_partition")
    matrix = np.asarray([row for race in selected for row in race.features], dtype=np.float64)
    if memory_bytes() + matrix.nbytes * 4 > config.raw["limits"]["memory_bytes"]:
        raise ResearchError("model_memory_budget")
    target = np.asarray([int(rank == 1) for race in selected for rank in dataset.outcomes[race.race_key].ranks])
    if len(np.unique(target)) != 2:
        raise ResearchError("training_requires_two_classes")
    models = {}
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        for variant, width in (("basic", 8), ("cross", 9)):
            pipeline = make_pipeline(StandardScaler(), LogisticRegression(
                C=config.raw["model"]["C"], solver=config.raw["model"]["solver"],
                max_iter=config.raw["model"]["max_iter"], random_state=config.raw["seed"],
            ))
            try:
                pipeline.fit(matrix[:, :width], target)
            except ConvergenceWarning:
                raise ResearchError("model_did_not_converge") from None
            contract = feature_contract(variant, dataset.provenance["build_identity_sha256"])
            models[variant] = {"contract": contract, "contract_sha256": digest(contract), "pipeline": pipeline,
                               "training_races": len(selected), "training_max_date": max(r.race_date for r in selected)}
            check_memory(config.raw["limits"]["memory_bytes"])
    return models


def probabilities(artifact: dict, race: InputRace, *, build_identity_sha256: str) -> np.ndarray:
    """結果へアクセスせず契約を照合して正規化確率を返す。"""
    if not isinstance(artifact, dict) or not isinstance(artifact.get("contract"), dict) or "pipeline" not in artifact:
        raise ResearchError("model_feature_contract_mismatch", 2)
    contract = artifact["contract"]
    expected = feature_contract(contract.get("variant"), build_identity_sha256)
    if contract != expected or artifact.get("contract_sha256") != digest(expected):
        raise ResearchError("model_feature_contract_mismatch", 2)
    width = len(expected["feature_names"])
    pipeline = artifact["pipeline"]
    if getattr(pipeline, "n_features_in_", None) != width or not callable(getattr(pipeline, "predict_proba", None)):
        raise ResearchError("model_feature_contract_mismatch", 2)
    matrix = np.asarray(race.features, dtype=np.float64)[:, :width]
    with threadpool_limits(limits=1):
        values = pipeline.predict_proba(matrix)[:, 1]
    if not np.isfinite(values).all() or np.any(values < 0) or values.sum() <= 0:
        raise ResearchError("invalid_probability")
    return values / values.sum()


def settle_win(status: str, stake_yen: int, payout_per_100: int | None) -> dict:
    """単勝の公式払戻・返還を100円単位の賭金へ適用する。

    Args:
        status: official_HR_payoutまたはrefund。
        stake_yen: 100円の正の整数倍の購入金額。
        payout_per_100: 100円当り払戻円。フラグや倍率を渡さない。

    Returns:
        賭金・払戻・損益・返還状態。

    Raises:
        ResearchError: 単位不正または精算状態不明。
    """
    if type(stake_yen) is not int or stake_yen <= 0 or stake_yen % 100:
        raise ResearchError("invalid_stake", 2)
    if status == "refund":
        payout = stake_yen
    elif status == "official_HR_payout" and type(payout_per_100) is int and payout_per_100 >= 0:
        payout = payout_per_100 * (stake_yen // 100)
    else:
        raise ResearchError("settlement_unknown")
    return {"stake_yen": stake_yen, "payout_yen": payout, "net_yen": payout - stake_yen, "refund": status == "refund"}


def ticket(race: InputRace, probs: np.ndarray, outcome: OutcomeBundle, settings: dict) -> dict | None:
    """結果を選択条件へ使わず最大1点を選び、選択後に公式払戻で精算する。"""
    candidates = [i for i, price in enumerate(race.odds) if settings["odds_min"] <= price <= settings["odds_max"]
                  and probs[i] * price >= settings["min_expected_return"]]
    if not candidates:
        return None
    index = min(candidates, key=lambda i: (-float(probs[i]) * race.odds[i], race.horses[i]))
    return {"horse_no": race.horses[index], "expected_multiplier": float(probs[index]) * race.odds[index],
            **settle_win("official_HR_payout", settings["stake_yen"], outcome.payouts[index])}


def summarize(rows: list[dict]) -> dict:
    """レース等重み精度・固定bin校正・時系列の損失と単勝成績を集計する。"""
    calibration = [{"count": 0, "sum_p": 0.0, "sum_y": 0.0} for _ in range(10)]
    loss, brier, stake, paid, hits, tickets, cumulative, peak, worst, drawdown = [], [], 0, 0, 0, 0, 0, 0, 0, 0
    for row in sorted(rows, key=lambda r: (r["race_date"], r["race_key"])):
        p, y = np.asarray(row["probability"]), np.asarray(row["target"])
        loss.append(float(-np.sum(y * np.log(np.clip(p, 1e-15, 1)))))
        brier.append(float(np.sum((p - y) ** 2)))
        for probability, actual in zip(p, y, strict=True):
            item = calibration[min(9, int(probability * 10))]
            item["count"] += 1
            item["sum_p"] += float(probability)
            item["sum_y"] += float(actual)
        chosen = row["ticket"]
        if chosen:
            tickets += 1
            stake += chosen["stake_yen"]
            paid += chosen["payout_yen"]
            hits += chosen["payout_yen"] > 0
            cumulative += chosen["net_yen"]
            peak = max(peak, cumulative)
            worst = min(worst, cumulative)
            drawdown = max(drawdown, peak - cumulative)
    return {"races": len(rows), "log_loss": float(np.mean(loss)) if loss else None,
            "brier": float(np.mean(brier)) if brier else None, "tickets": tickets, "stake_yen": stake,
            "payout_yen": paid, "net_yen": paid - stake, "roi": paid / stake if stake else None,
            "hit_rate": hits / tickets if tickets else None, "maximum_cumulative_loss_yen": -worst,
            "maximum_drawdown_yen": drawdown, "calibration": [
                {"lower": i / 10, "upper": (i + 1) / 10, "count": c["count"],
                 "mean_probability": c["sum_p"] / c["count"] if c["count"] else None,
                 "mean_target": c["sum_y"] / c["count"] if c["count"] else None}
                for i, c in enumerate(calibration)]}


def evaluate(dataset: ResearchDataset, config: ResearchConfig, models: dict) -> tuple[dict, list[dict]]:
    """同じレース/馬集合でmarket/basic/crossを比較し、保存可能な予測を返す。"""
    groups, predictions = defaultdict(list), []
    for index, race in enumerate(dataset.races):
        if index % 100 == 0:
            check_memory(config.raw["limits"]["memory_bytes"])
        split = config.split(race.race_date)
        if split is None:
            continue
        outcome = dataset.outcomes[race.race_key]
        winners = np.asarray([rank == 1 for rank in outcome.ranks], dtype=float)
        target = winners / winners.sum()
        baseline = 1 / np.asarray(race.odds, dtype=float)
        variants = {"market": baseline / baseline.sum()}
        variants.update({variant: probabilities(model, race, build_identity_sha256=dataset.provenance["build_identity_sha256"])
                         for variant, model in models.items()})
        for name, probs in variants.items():
            chosen = ticket(race, probs, outcome, config.raw["ticket"])
            row = {"race_key": race.race_key, "race_date": race.race_date, "venue": race.venue,
                   "variant": name, "split": split, "horses": list(race.horses),
                   "probability": probs.tolist(), "target": target.tolist(), "ticket": chosen}
            groups[(split, name)].append(row)
            predictions.append(row)
    for split in ("train", "dev", "evaluation"):
        if not groups[(split, "market")]:
            raise ResearchError("empty_partition", 4, split=split)
    reports = {}
    for (split, name), rows in groups.items():
        by_year, by_venue = defaultdict(list), defaultdict(list)
        for row in rows:
            by_year[row["race_date"][:4]].append(row)
            by_venue[row["venue"]].append(row)
        reports.setdefault(split, {})[name] = {**summarize(rows),
            "by_year": {k: summarize(v) for k, v in by_year.items()},
            "by_venue": {k: summarize(v) for k, v in by_venue.items()}}
    return {"report_version": "jra-sql-evaluation-v1", "validation_kind": "retrospective",
            "same_day_order": "race_key_not_verified_start_order", "splits": reports}, predictions
