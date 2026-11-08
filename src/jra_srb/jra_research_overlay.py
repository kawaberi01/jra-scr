"""概要: 履歴オッズoverlay評価の純計算と日次特徴量作成を行う。
作成日: 2026-10-16
入力: レース・出走馬情報、独立した結果/払戻、単勝/ワイド価格。
出力: 特徴量行と50通りの候補評価、および学習済みモデル（メモリ上）。
実行例: uv run python -m pytest tests/test_jra_research_overlay.py
注意事項: DB・HTTP・ファイルI/Oは行わない。結果欠落の精算はunknownとする。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
import json
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from jra_srb.jra_research_contracts import ResearchError

TRAIN_END = "2025-06-30"
DEV_END = "2025-09-30"
CS = (0.01, 0.03, 0.1, 0.3, 1.0)
OVERLAY_THRESHOLDS = tuple(round(1.00 + 0.05 * i, 2) for i in range(10))
FEATURE_KEYS = (
    "starts", "avg_rank", "top3_rate", "recent_top3_rate", "recent_avg_rank",
    "same_surface_top3_rate", "same_course_top3_rate", "same_dist_top3_rate",
    "recent_corner_ratio", "recent_final_3f", "same_dist_final_3f", "recent_rank_std",
    "fast_pace_top3_rate", "same_surface_corner_ratio", "jockey_recent_top3_rate",
    "trainer_recent_top3_rate", "jockey_recent_same_surface_top3_rate",
    "trainer_recent_same_distance_bucket_top3_rate", "field_size", "race_no",
)


@dataclass(frozen=True)
class RunnerInput:
    """出走馬の特徴量生成に必要な当該レース属性を保持する。"""
    horse_no: str
    horse_name: str
    field_size: int
    race_no: int
    surface: str | None = None
    course: str | None = None
    distance: Any = None
    jockey: str | None = None
    trainer: str | None = None
    corner_order: str | None = None
    final_3f: float | None = None
    race_laps_json: str | None = None


@dataclass(frozen=True)
class RaceInput:
    """同日更新単位となるレースと出走馬を表す。"""
    race_id: str
    race_date: str
    runners: tuple[RunnerInput, ...]


@dataclass(frozen=True)
class Outcome:
    """独立した確定結果と払戻を表す。未確定値はNoneで保持する。"""
    rank: int | None
    win_payout: int | None = None
    wide_payouts: Mapping[tuple[str, str], int] | None = None


@dataclass(frozen=True)
class OverlayRow:
    """学習・予測で利用する結果非依存の入力行を保持する。"""
    race_id: str
    race_date: str
    selection_key: str | tuple[str, str]
    features: tuple[float | None, ...]
    market_probability: float
    price: float
    kind: str


@dataclass(frozen=True)
class OverlayDataset:
    """入力行、学習target、精算値を同じ添字で別々に保持する。"""
    rows: tuple[OverlayRow, ...]
    targets: tuple[int | None, ...]
    settlements: tuple[int | None, ...]


@dataclass(frozen=True)
class HistoryBundle:
    """過去の馬・騎手・調教師結果を保持する。"""
    horses: Mapping[str, list[dict[str, Any]]]
    jockeys: Mapping[str, list[dict[str, Any]]]
    trainers: Mapping[str, list[dict[str, Any]]]


def norm_dist(value: Any) -> int | None:
    """距離表記から数字だけを取り出し、距離メートルを返す。"""
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def distance_bucket(dist: int | None) -> str:
    """距離を旧評価と同じ5区分のラベルへ変換する。"""
    if dist is None:
        return "missing"
    if dist <= 1400:
        return "sprint"
    if dist <= 1800:
        return "mile"
    if dist <= 2200:
        return "intermediate"
    return "long"


def hist_features(hist: Sequence[Mapping[str, Any]], race: Mapping[str, Any], history: HistoryBundle) -> dict[str, Any]:
    """旧履歴評価の20特徴量を、当該レース以前の履歴だけから計算する。"""
    starts = len(hist)
    corner_ratios, closing_times = [], []
    for item in hist[-5:]:
        corner = str(item.get("corner_order") or "").split("-")
        if corner and corner[-1].isdigit() and item.get("field_size"):
            corner_ratios.append(int(corner[-1]) / int(item["field_size"]))
        if item.get("final_3f") is not None:
            closing_times.append(float(item["final_3f"]))
    ranks = [int(item["rank"]) for item in hist if item.get("rank")]
    top3 = sum(rank <= 3 for rank in ranks)
    recent = list(hist[-5:])
    recent_ranks = [int(item["rank"]) for item in recent if item.get("rank")]
    recent_rank_std = pstdev(recent_ranks) if len(recent_ranks) >= 2 else None
    recent_top3 = sum(rank <= 3 for rank in recent_ranks)
    surface, course = race.get("surface"), race.get("course")
    same_surface = [item for item in hist if surface and item.get("surface") == surface]
    same_surface_corner_ratios = []
    for item in same_surface[-5:]:
        corner = str(item.get("corner_order") or "").split("-")
        if corner and corner[-1].isdigit() and item.get("field_size"):
            same_surface_corner_ratios.append(int(corner[-1]) / int(item["field_size"]))
    same_course = [item for item in hist if course and item.get("course") == course]
    same_surface_top3 = sum(1 for item in same_surface if int(item["rank"]) <= 3)
    same_course_top3 = sum(1 for item in same_course if int(item["rank"]) <= 3)
    dist = norm_dist(race.get("distance"))
    same_dist = [item for item in hist if dist and norm_dist(item.get("distance")) and abs(norm_dist(item.get("distance")) - dist) <= 200]
    same_dist_top3 = sum(1 for item in same_dist if int(item["rank"]) <= 3)
    fast_pace = []
    for item in hist:
        try:
            laps = [float(x) for x in json.loads(item.get("race_laps_json") or "[]")]
        except (TypeError, ValueError):
            laps = []
        if len(laps) >= 4 and mean(laps[: len(laps) // 2]) - mean(laps[len(laps) // 2 :]) <= -0.3:
            fast_pace.append(item)
    fast_pace_top3 = sum(1 for item in fast_pace if int(item["rank"]) <= 3)
    same_dist_final3f = [float(item["final_3f"]) for item in same_dist if item.get("final_3f") is not None]
    jockey = str(race.get("jockey") or "")
    trainer = str(race.get("trainer") or "")
    jockey_recent = list(history.jockeys.get(jockey, [])[-20:]) if jockey else []
    trainer_recent = list(history.trainers.get(trainer, [])[-20:]) if trainer else []
    jockey_surface = [item for item in jockey_recent if surface and item.get("surface") == surface]
    target_bucket = distance_bucket(dist)
    trainer_bucket = [item for item in trainer_recent if distance_bucket(norm_dist(item.get("distance"))) == target_bucket]
    jr3 = sum(int(item["rank"]) <= 3 for item in jockey_recent)
    tr3 = sum(int(item["rank"]) <= 3 for item in trainer_recent)
    js3 = sum(int(item["rank"]) <= 3 for item in jockey_surface)
    tb3 = sum(int(item["rank"]) <= 3 for item in trainer_bucket)
    return {
        "starts": starts, "avg_rank": mean(ranks) if ranks else 99.0,
        "top3_rate": top3 / starts if starts else 0.0,
        "recent_top3_rate": recent_top3 / len(recent) if recent else 0.0,
        "recent_avg_rank": mean(recent_ranks) if recent_ranks else 99.0,
        "same_surface_top3_rate": same_surface_top3 / len(same_surface) if same_surface else None,
        "same_course_top3_rate": same_course_top3 / len(same_course) if same_course else None,
        "same_dist_top3_rate": same_dist_top3 / len(same_dist) if same_dist else None,
        "recent_corner_ratio": mean(corner_ratios) if corner_ratios else None,
        "recent_final_3f": mean(closing_times) if closing_times else None,
        "same_dist_final_3f": mean(same_dist_final3f[-5:]) if same_dist_final3f else None,
        "recent_rank_std": recent_rank_std,
        "fast_pace_top3_rate": fast_pace_top3 / len(fast_pace) if fast_pace else None,
        "same_surface_corner_ratio": mean(same_surface_corner_ratios) if same_surface_corner_ratios else None,
        "jockey_recent_top3_rate": jr3 / len(jockey_recent) if jockey_recent else None,
        "trainer_recent_top3_rate": tr3 / len(trainer_recent) if trainer_recent else None,
        "jockey_recent_same_surface_top3_rate": js3 / len(jockey_surface) if jockey_surface else None,
        "trainer_recent_same_distance_bucket_top3_rate": tb3 / len(trainer_bucket) if trainer_bucket else None,
        "field_size": float(race.get("field_size") or 0), "race_no": float(race.get("race_no") or 0),
        "surface": surface, "distance_bucket": distance_bucket(dist),
    }


def pair_features(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[float | None, ...]:
    """旧仕様どおり各特徴量を2頭のmin/max順に並べる。"""
    values: list[float | None] = []
    for key in FEATURE_KEYS:
        a, b = _as_float(left.get(key)), _as_float(right.get(key))
        values.extend((a, b) if a is None or b is None else (min(a, b), max(a, b)))
    return tuple(values)


def _as_float(value: Any) -> float | None:
    """数値化できる値をfloatにし、それ以外を欠損として返す。"""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _require_finite_number(value: Any, reason: str) -> float:
    """boolを除く有限数だけを受け付け、違反を共通ResearchErrorにする。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)) or not np.isfinite(value):
        raise ResearchError(reason)
    return float(value)


def build_rows(races: Sequence[RaceInput], win_prices: Mapping[tuple[str, str], float], wide_prices: Mapping[tuple[str, tuple[str, str]], float], outcomes: Mapping[tuple[str, str], Outcome]) -> OverlayDataset:
    """2025年をcold startし、同日結果を同日特徴量へ混入させず行を作る。"""
    by_date: dict[str, list[RaceInput]] = defaultdict(list)
    for race in races:
        if not race.race_date.startswith("2025-"):
            continue
        by_date[race.race_date].append(race)
    horses: dict[str, list[dict[str, Any]]] = defaultdict(list)
    jockeys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trainers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[OverlayRow] = []
    targets: list[int | None] = []
    settlements: list[int | None] = []
    for race_date in sorted(by_date):
        day = sorted(by_date[race_date], key=lambda item: item.race_id)
        for race in day:
            runner_rows: dict[str, tuple[RunnerInput, dict[str, Any], Outcome | None]] = {}
            for runner in race.runners:
                hist_record = {"surface": runner.surface, "course": runner.course, "distance": runner.distance,
                               "field_size": runner.field_size, "race_no": runner.race_no, "jockey": runner.jockey,
                               "trainer": runner.trainer}
                features = hist_features(horses[runner.horse_name], hist_record, HistoryBundle(horses, jockeys, trainers))
                out = outcomes.get((race.race_id, runner.horse_no))
                runner_rows[runner.horse_no] = (runner, features, out)
                odds = win_prices.get((race.race_id, runner.horse_no))
                if odds is not None and odds > 0:
                    rows.append(OverlayRow(race.race_id, race_date, runner.horse_no,
                                           tuple(_as_float(features.get(k)) for k in FEATURE_KEYS),
                                           0.80 / odds, odds, "win"))
                    targets.append(int(out.rank == 1) if out and out.rank is not None else None)
                    settlements.append(out.win_payout if out else None)
            nos = sorted(runner_rows, key=int)
            for left_no, right_no in combinations(nos, 2):
                pair = (left_no, right_no)
                odds = wide_prices.get((race.race_id, pair))
                if odds is None or odds <= 0:
                    continue
                left, right = runner_rows[left_no], runner_rows[right_no]
                lo, ro = left[2], right[2]
                payout = None
                if lo and lo.wide_payouts is not None and pair in lo.wide_payouts:
                    payout = lo.wide_payouts[pair]
                rows.append(OverlayRow(race.race_id, race_date, pair, pair_features(left[1], right[1]),
                                       0.775 / odds, odds, "wide"))
                targets.append(int(lo.rank <= 3 and ro.rank <= 3) if lo and ro and lo.rank is not None and ro.rank is not None else None)
                settlements.append(payout)
        for race in day:
            for runner in race.runners:
                out = outcomes.get((race.race_id, runner.horse_no))
                if out is None or out.rank is None:
                    continue
                record = {"horse_name": runner.horse_name, "rank": out.rank, "surface": runner.surface,
                          "course": runner.course, "distance": runner.distance, "field_size": runner.field_size,
                          "race_no": runner.race_no, "jockey": runner.jockey, "trainer": runner.trainer,
                          "corner_order": runner.corner_order, "final_3f": runner.final_3f,
                          "race_laps_json": runner.race_laps_json}
                horses[runner.horse_name].append(record)
                if runner.jockey:
                    jockeys[runner.jockey].append(record)
                if runner.trainer:
                    trainers[runner.trainer].append(record)
    return OverlayDataset(tuple(rows), tuple(targets), tuple(settlements))


def select(rows: Sequence[OverlayRow], probabilities: Sequence[float], threshold: float) -> list[OverlayRow]:
    """結果・払戻に触れず、確率比だけでレースごとの候補を選ぶ。"""
    if len(rows) != len(probabilities):
        raise ResearchError("probability_count_mismatch")
    kinds = {row.kind for row in rows}
    if len(kinds) > 1 or (kinds and not kinds <= {"win", "wide"}):
        raise ResearchError("invalid_overlay_kind")
    seen: set[tuple[str, str | tuple[str, str]]] = set()
    for row, probability in zip(rows, probabilities, strict=True):
        if not isinstance(row.selection_key, str) and not (
            isinstance(row.selection_key, tuple) and len(row.selection_key) == 2
            and all(isinstance(part, str) for part in row.selection_key)
        ):
            raise ResearchError("invalid_overlay_selection_key")
        identity = (row.race_id, row.selection_key)
        if identity in seen:
            raise ResearchError("duplicate_overlay_selection")
        seen.add(identity)
        p = _require_finite_number(probability, "invalid_overlay_probability")
        if not 0 <= p <= 1:
            raise ResearchError("invalid_overlay_probability")
        price = _require_finite_number(row.price, "invalid_overlay_price")
        if price <= 0:
            raise ResearchError("invalid_overlay_price")
        market_probability = _require_finite_number(row.market_probability, "invalid_market_probability")
        if market_probability <= 0:
            raise ResearchError("invalid_market_probability")
    threshold = _require_finite_number(threshold, "invalid_overlay_threshold")
    if threshold <= 0:
        raise ResearchError("invalid_overlay_threshold")
    by_race: dict[str, list[tuple[OverlayRow, float]]] = defaultdict(list)
    for row, probability in zip(rows, probabilities, strict=True):
        if row.kind == "wide":
            in_band = 3.0 <= 0.775 / row.market_probability <= 20.0
        else:
            in_band = 3.0 <= row.price <= 30.0
        if in_band:
            by_race[row.race_id].append((row, float(probability) / row.market_probability))
    selected = []
    for candidates in by_race.values():
        row, overlay = max(candidates, key=lambda item: item[1])
        if overlay >= threshold:
            selected.append(row)
    return selected


def summarize(rows: Sequence[OverlayRow], probabilities: Sequence[float], settlements: Sequence[int | None], threshold: float) -> dict[str, Any]:
    """入力だけで候補を選び、別配列の精算値でsummary指標を計算する。"""
    if len(rows) != len(probabilities) or len(rows) != len(settlements):
        raise ResearchError("summary_input_count_mismatch")
    if any(value is not None and (type(value) is not int or value < 0) for value in settlements):
        raise ResearchError("invalid_overlay_settlement")
    selected = select(rows, probabilities, threshold)
    settlement_by_identity = {id(row): amount for row, amount in zip(rows, settlements, strict=True)}
    selected_settlements = [settlement_by_identity[id(row)] for row in selected]
    unknown = sum(amount is None for amount in selected_settlements)
    payouts = [int(amount) for amount in selected_settlements if amount is not None]
    total_bet = len(selected) * 100
    ordered = sorted(payouts)
    without_max = sum(ordered[:-1]) if ordered else 0
    without_top3 = sum(ordered[:-3]) if len(ordered) > 3 else 0
    return {"tickets": len(selected), "hits": None if unknown else sum(p > 0 for p in payouts),
            "return_rate": None if unknown else (round(sum(payouts) / total_bet, 4) if total_bet else 0.0),
            "no_max_return_rate": None if unknown else (round(without_max / max(total_bet - 100, 1), 4) if total_bet > 1 else 0.0),
            "no_top3_return_rate": None if unknown else (round(without_top3 / max(total_bet - min(3, len(selected)) * 100, 1), 4) if len(selected) > 3 else 0.0),
            "max_payout": None if unknown else max(payouts, default=0),
            "settlement_unknown": unknown}


def evaluate(dataset: OverlayDataset) -> dict[str, Any]:
    """時系列分割で5モデルを学習し、50候補の旧summary相当を返す。"""
    if not (len(dataset.rows) == len(dataset.targets) == len(dataset.settlements)):
        raise ResearchError("dataset_alignment_mismatch")
    kinds = {row.kind for row in dataset.rows}
    if len(kinds) != 1 or not kinds <= {"win", "wide"}:
        raise ResearchError("single_overlay_profile_required")
    name_prefix = "win_overlay" if kinds == {"win"} else "overlay"
    expected_width = 20 if name_prefix == "win_overlay" else 40
    if any(len(row.features) != expected_width for row in dataset.rows):
        raise ResearchError("overlay_feature_width_mismatch")
    indexed = list(zip(dataset.rows, dataset.targets, dataset.settlements, strict=True))
    train_all = [(row, target, payout) for row, target, payout in indexed if row.race_date <= TRAIN_END]
    if not train_all or any(target is None for _, target, _ in train_all):
        raise ResearchError("training_target_missing")
    if any(target not in (0, 1) for _, target, _ in train_all):
        raise ResearchError("invalid_training_target")
    train = train_all
    dev = [(row, target, payout) for row, target, payout in indexed if TRAIN_END < row.race_date <= DEV_END]
    holdout = [(row, target, payout) for row, target, payout in indexed if row.race_date > DEV_END]
    if not dev or not holdout:
        raise ResearchError(f"insufficient_temporal_split:{len(train)}/{len(dev)}/{len(holdout)}")
    candidates = []
    models = {}
    for c_value in CS:
        train_rows = [row for row, _, _ in train]
        dev_rows = [row for row, _, _ in dev]
        holdout_rows = [row for row, _, _ in holdout]
        model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                              LogisticRegression(C=c_value, max_iter=500, random_state=0))
        model.fit(_matrix(train_rows), np.asarray([target for _, target, _ in train]))
        models[c_value] = model
        dp = model.predict_proba(_matrix(dev_rows))[:, 1]
        hp = model.predict_proba(_matrix(holdout_rows))[:, 1]
        for threshold in OVERLAY_THRESHOLDS:
            ds = summarize(dev_rows, dp, [payout for _, _, payout in dev], threshold)
            hs = summarize(holdout_rows, hp, [payout for _, _, payout in holdout], threshold)
            candidates.append({"name": f"{name_prefix}_c{c_value:g}_t{threshold:.2f}",
                               "C": c_value, "overlay_threshold": threshold, "dev": ds, "holdout": hs,
                               "dev_pass": ds["return_rate"] is not None and ds["tickets"] >= 60 and ds["return_rate"] >= 1 and ds["no_max_return_rate"] >= 1,
                               "holdout_pass": hs["return_rate"] is not None and hs["tickets"] >= 60 and hs["return_rate"] >= 1 and hs["no_max_return_rate"] >= 1 and hs["no_top3_return_rate"] >= 1})
    return {"splits": {"train_end": TRAIN_END, "dev_end": DEV_END},
            "rows": {"train": len(train), "dev": len(dev), "holdout": len(holdout)},
            "candidate_count": len(candidates), "candidates": candidates,
            "eligible": [x for x in candidates if x["dev_pass"] and x["holdout_pass"]], "models": models}


def _matrix(rows: Sequence[OverlayRow]) -> np.ndarray:
    """モデル入力行を欠損対応のNumPy行列に変換する。"""
    return np.asarray([[np.nan if value is None else
                        _require_finite_number(value, "nonfinite_overlay_feature")
                        for value in row.features] for row in rows])
