"""概要: overlay純計算の旧式同値と入出力境界を検証する。
作成日: 2026-10-16
入力: 固定された旧script/evaluator内の純関数定義と合成fixture。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_research_overlay.py
注意事項: 旧script全体やDBをimportせず、ASTから指定純関数だけを読み込む。
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import numpy as np
import pytest

from jra_srb import jra_research_overlay as overlay
from jra_srb.jra_research_contracts import ResearchError

ROOT = Path(__file__).resolve().parents[1]


def _extract(path: Path, names: set[str], namespace: dict[str, Any]) -> dict[str, Any]:
    """指定ファイルから列挙したAST定義だけを実行して返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    def declared(node: ast.stmt) -> set[str]:
        """AST文から定義名を列挙する。"""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return {node.name}
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            return {target.id for target in targets if isinstance(target, ast.Name)}
        return set()
    selected = [node for node in tree.body if declared(node) & names]
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def _legacy_overlay() -> dict[str, Any]:
    """旧wide scriptの定数と純関数だけをASTで取り出す。"""
    names = {"FEATURE_KEYS", "MIN_WIDE_ODDS", "MAX_WIDE_ODDS", "TAKE_RATE", "PairRow", "_as_float", "_pair_features", "_summary"}
    return _extract(ROOT / "scripts/evaluate_market_price_overlay.py", names,
                    {"Any": Any, "dataclass": dataclass, "defaultdict": defaultdict, "np": np})


def _legacy_history() -> dict[str, Any]:
    """旧evaluatorから履歴特徴量に必要な定義だけをASTで取り出す。"""
    names = {"HistoryBundle", "norm_dist", "distance_bucket", "hist_features"}
    return _extract(ROOT / ".workstate/jra-srb/prediction-v1-validation/evaluate_v1_validation.py", names,
                    {"Any": Any, "dataclass": dataclass, "json": json, "mean": mean, "pstdev": pstdev})


def _legacy_win() -> dict[str, Any]:
    """旧win scriptのsummary関数と必要な型・定数だけをASTで取り出す。"""
    names = {"MIN_WIN_ODDS", "MAX_WIN_ODDS", "HorseRow", "_summary"}
    return _extract(ROOT / "scripts/evaluate_win_price_overlay.py", names,
                    {"Any": Any, "dataclass": dataclass, "defaultdict": defaultdict, "np": np})


def test_old_pair_and_summary_match_and_feature_dimensions() -> None:
    """旧AST純関数とpair特徴量・既知払戻summaryを比較する。"""
    old = _legacy_overlay()
    left = {key: i + 0.25 for i, key in enumerate(overlay.FEATURE_KEYS)}
    right = {key: i + 1.75 for i, key in enumerate(overlay.FEATURE_KEYS)}
    assert len(overlay.FEATURE_KEYS) == 20
    assert len(overlay.pair_features(left, right)) == 40
    assert overlay.pair_features(left, right) == old["_pair_features"](left, right)
    rows = []
    old_rows = []
    for index, payout in enumerate((0, 180, 420, 0)):
        features = (float(index),) * 40
        row = overlay.OverlayRow(f"r{index}", "2025-10-02", ("1", "2"), features, 0.775 / 5, 5, "wide")
        rows.append(row)
        old_rows.append(old["PairRow"](row.race_id, row.race_date, row.selection_key, row.features,
                                        index % 2, row.market_probability, payout))
    probabilities = np.asarray([0.4, 0.8, 0.6, 0.7])
    expected = old["_summary"](old_rows, probabilities, 1.0)
    actual = overlay.summarize(rows, probabilities, (0, 180, 420, 0), 1.0)
    assert {key: actual[key] for key in expected} == expected


def test_win_summary_legacy_counts_ties_threshold_and_odds_band() -> None:
    """旧win summaryと0/1/3/4件、同点、閾値・価格帯境界を照合する。"""
    old = _legacy_win()
    for count in (0, 1, 3, 4):
        rows = []
        legacy_rows = []
        probs = []
        settlements = []
        odds = (3.0, 30.0, 2.99, 30.01)[:count]
        for idx, price in enumerate(odds):
            row = overlay.OverlayRow(f"r{idx}", "2025-10-01", str(idx + 1), (0.0,) * 20,
                                     0.8 / price, price, "win")
            payout = (0, 100, 300, 900)[idx]
            probability = row.market_probability
            rows.append(row)
            legacy_rows.append(old["HorseRow"](row.race_id, row.race_date, row.selection_key,
                                                row.features, idx % 2, row.market_probability, price, payout))
            probs.append(probability)
            settlements.append(payout)
        expected = old["_summary"](legacy_rows, np.asarray(probs), 1.0)
        actual = overlay.summarize(rows, probs, settlements, 1.0)
        assert {key: actual[key] for key in expected} == expected
    tie_rows = [
        overlay.OverlayRow("same", "2025-10-01", "1", (0.0,) * 20, 0.8 / 5, 5, "win"),
        overlay.OverlayRow("same", "2025-10-01", "2", (0.0,) * 20, 0.8 / 5, 5, "win"),
    ]
    tie_probs = [0.16, 0.16]
    expected = old["_summary"](
        [old["HorseRow"](row.race_id, row.race_date, row.selection_key, row.features, 0,
                          row.market_probability, row.price, payout)
         for row, payout in zip(tie_rows, (700, 900), strict=True)], np.asarray(tie_probs), 1.0)
    actual = overlay.summarize(tie_rows, tie_probs, (700, 900), 1.0)
    assert {key: actual[key] for key in expected} == expected
    assert overlay.summarize(tie_rows, tie_probs, (700, 900), 1.01)["tickets"] == 0
    wide_rows = [overlay.OverlayRow(f"w{i}", "2025-10-01", (str(i), str(i + 1)), (0.0,) * 40,
                                    0.775 / price, price, "wide") for i, price in enumerate((3.0, 20.0))]
    wide_old = _legacy_overlay()
    old_summary = wide_old["_summary"](
        [wide_old["PairRow"](row.race_id, row.race_date, row.selection_key, row.features, 0,
                             row.market_probability, 0) for row in wide_rows], np.asarray([0.5, 0.5]), 0.01)
    wide_summary = overlay.summarize(wide_rows, [0.5, 0.5], [0, 0], 0.01)
    assert {key: wide_summary[key] for key in old_summary} == old_summary


def test_input_validation_and_unknown_settlement_are_fail_closed() -> None:
    """不正な候補・精算型を拒否し、unknown時は最大払戻も不明にする。"""
    row = overlay.OverlayRow("r", "2025-10-01", "1", (None,) * 20, 0.16, 5.0, "win")
    with pytest.raises(overlay.ResearchError):
        overlay.select([row, row], [0.5, 0.5], 1.0)
    for bad_probability in (float("nan"), 1.01):
        with pytest.raises(overlay.ResearchError):
            overlay.select([row], [bad_probability], 1.0)
    for bad_row in (row.__class__("r", "2025-10-01", "1", row.features, 0.16, 0, "win"),
                    row.__class__("r", "2025-10-01", "1", row.features, float("inf"), 5, "win"),
                    row.__class__("r", "2025-10-01", "1", row.features, 0.16, 5, "other")):
        with pytest.raises(overlay.ResearchError):
            overlay.select([bad_row], [0.5], 1.0)
    mixed = [row, overlay.OverlayRow("r2", "2025-10-01", ("1", "2"), (None,) * 40, 0.1, 7, "wide")]
    with pytest.raises(overlay.ResearchError):
        overlay.select(mixed, [0.5, 0.5], 1.0)
    for bad_settlement in (-1, 1.5, True):
        with pytest.raises(overlay.ResearchError):
            overlay.summarize([row], [0.5], [bad_settlement], 1.0)
    unknown = overlay.summarize([row], [0.5], [None], 1.0)
    assert unknown["tickets"] == 1
    assert unknown["max_payout"] is None
    empty = overlay.summarize([], [], [], 1.0)
    assert empty["tickets"] == 0 and empty["return_rate"] == 0.0
    train_row = overlay.OverlayRow("r", "2025-01-01", "1", (None,) * 19, 0.16, 5.0, "win")
    wrong_width = overlay.OverlayDataset((train_row,), (1,), (100,))
    with pytest.raises(ResearchError, match="overlay_feature_width_mismatch"):
        overlay.evaluate(wrong_width)
    nonfinite_feature = overlay.OverlayRow("r", "2025-01-01", "1", (float("inf"),) + (None,) * 19,
                                           0.16, 5, "win")
    with pytest.raises(ResearchError, match="nonfinite_overlay_feature"):
        overlay._matrix([nonfinite_feature])


def test_daily_cold_start_same_day_isolation_and_unknown_settlement() -> None:
    """同日結果漏洩を防ぎ、未確定払戻をunknownとして保持する。"""
    races = [
        overlay.RaceInput("r1", "2025-01-02", (overlay.RunnerInput("1", "horse-a", 2, 1, "turf", "kyoto", 1600),
                                                    overlay.RunnerInput("2", "horse-b", 2, 1, "turf", "kyoto", 1600))),
        overlay.RaceInput("r2", "2025-01-02", (overlay.RunnerInput("1", "horse-a", 2, 2, "turf", "kyoto", 1600),
                                                    overlay.RunnerInput("2", "horse-c", 2, 2, "turf", "kyoto", 1600))),
        overlay.RaceInput("r3", "2025-01-03", (overlay.RunnerInput("1", "horse-a", 2, 1, "turf", "kyoto", 1600),
                                                    overlay.RunnerInput("2", "horse-d", 2, 1, "turf", "kyoto", 1600))),
    ]
    prices = {(race.race_id, runner.horse_no): 5.0 for race in races for runner in race.runners}
    outcomes = {(race.race_id, runner.horse_no): overlay.Outcome(1 if runner.horse_no == "1" else 4, 200)
                for race in races for runner in race.runners}
    dataset = overlay.build_rows(races, prices, {}, outcomes)
    first_day = [row for row in dataset.rows if row.race_date == "2025-01-02"]
    assert all(row.features[0] == 0 for row in first_day)
    changed = dict(outcomes)
    changed[("r3", "1")] = overlay.Outcome(9, 9999)
    rebuilt = overlay.build_rows(races, prices, {}, changed)
    assert [row for row in dataset.rows if row.race_date == "2025-01-02"] == [row for row in rebuilt.rows if row.race_date == "2025-01-02"]
    unknown_rows = overlay.build_rows(races[:1], prices, {}, {})
    selected_summary = overlay.summarize([unknown_rows.rows[0]], [0.99], [unknown_rows.settlements[0]], 1.0)
    assert selected_summary["tickets"] == 1
    assert selected_summary["settlement_unknown"] == 1
    assert selected_summary["return_rate"] is None


def test_hist_features_match_and_evaluation_returns_fifty_candidates() -> None:
    """旧履歴featureと一致し、5C×10thresholdの50候補を返す。"""
    old = _legacy_history()
    past = [{"rank": 2, "surface": "turf", "course": "kyoto", "distance": "芝1600m", "field_size": 12,
             "corner_order": "1-2-3", "final_3f": 34.5, "race_laps_json": "[12,12,12,11]"}]
    race = {"surface": "turf", "course": "kyoto", "distance": "芝1800m", "field_size": 10,
            "race_no": 7, "jockey": "j1", "trainer": "t1"}
    old_bundle = old["HistoryBundle"]({"h": past}, {"j1": past}, {"t1": past})
    new_bundle = overlay.HistoryBundle({"h": past}, {"j1": past}, {"t1": past})
    assert overlay.hist_features(past, race, new_bundle) == old["hist_features"](past, race, old_bundle)
    missing_race = {"surface": None, "course": None, "distance": None, "field_size": None,
                    "race_no": None, "jockey": None, "trainer": None}
    assert overlay.hist_features([], missing_race, new_bundle) == old["hist_features"]([], missing_race, old_bundle)
    rows = []
    for idx in range(90):
        date = "2025-05-01" if idx < 30 else "2025-08-01" if idx < 60 else "2025-11-01"
        target = idx % 2
        features = tuple(float((idx + j) % 7) for j in range(20))
        rows.append(overlay.OverlayRow(f"r{idx}", date, "1", features, 0.8 / 5, 5, "win"))
    dataset = overlay.OverlayDataset(tuple(rows), tuple(idx % 2 for idx in range(90)),
                                    tuple(200 if idx % 2 else 0 for idx in range(90)))
    report = overlay.evaluate(dataset)
    assert report["candidate_count"] == 50
    assert len(report["candidates"]) == 50
    assert set(report["models"]) == set(overlay.CS)
    outcome_blind_targets = tuple(target if rows[idx].race_date <= overlay.TRAIN_END else None for idx, target in enumerate(dataset.targets))
    blinded = overlay.evaluate(overlay.OverlayDataset(dataset.rows, outcome_blind_targets, dataset.settlements))
    assert report["rows"] == blinded["rows"] == {"train": 30, "dev": 30, "holdout": 30}
    assert [(item["dev"]["tickets"], item["holdout"]["tickets"]) for item in report["candidates"]] == [
        (item["dev"]["tickets"], item["holdout"]["tickets"]) for item in blinded["candidates"]]
    missing_train = tuple(None if rows[idx].race_date <= overlay.TRAIN_END else dataset.targets[idx] for idx in range(90))
    with pytest.raises(ResearchError, match="training_target_missing"):
        overlay.evaluate(overlay.OverlayDataset(dataset.rows, missing_train, dataset.settlements))
