"""概要: キメラの時計・時点分離・縮約・馬連尤度と固定判定を検証する。
作成日: 2026-10-18
入力: 合成の過去走・特徴・競走別損失。SQL接続なし。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_chimera.py
注意事項: 実データの学習や当日予想への接続はしない。
"""

from copy import deepcopy
import math

import numpy as np
import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_chimera import (States, accuracy_gate, clock_seconds, fit, objective,
                                         pair_features, pairs, predict, purchase_gate,
                                         centers_for, pack_training, packed_objective)
from jra_srb import jra_research_tipster_twenty as native
from jra_srb import jra_research_tipster_residual as residual


def race(day=10):
    """時計・脚質の異なる8頭の合成競走を作る。"""
    return {"ordinal": day, "day": "2024-01-10", "surface": 0, "distance": 1600, "course": 5, "pace": -.8,
            "runners": [{"horse_id": str(i), "horse_no": f"{i + 1:02d}", "rank": i + 1, "corner": i + 1} for i in range(8)]}


def test_clock_unit_and_invalid_seconds():
    """分秒0.1秒の桁を独立に確認し、60秒表記・空欄を拒否する。"""
    assert clock_seconds(b"1122") == 72.2
    assert clock_seconds(b"2345") == 154.5
    for invalid in (b"1600", b"0000", b"    ", b"122"):
        with pytest.raises(ResearchError):
            clock_seconds(invalid)


def test_public_features_ignore_current_results_and_pace():
    """現在の着順・時計相当値・実ペースを変えても予測入力は変えない。"""
    states = States()
    past = race(1)
    states.update_day([(past, {r["horse_no"]: 95 + i for i, r in enumerate(past["runners"])}, 1)])
    current = race(10)
    original = states.public(current)
    changed = deepcopy(current)
    changed["pace"] = 100
    for r in changed["runners"]:
        r.update(rank=999, corner=99, clock=1)
    for name, value in original.items():
        assert np.array_equal(value, states.public(changed)[name])


def test_same_day_history_is_rejected():
    """同日更新済みの結果を当日の特徴へ使う呼出を拒否する。"""
    states, current = States(), race(10)
    states.update_day([(current, {r["horse_no"]: 95 + i for i, r in enumerate(current["runners"])}, 1)])
    with pytest.raises(ResearchError):
        states.public(current)


def test_unseen_horses_shrink_to_zero_without_dropping_runners():
    """新馬の観測不足は事前値と信頼度へ表し、馬を削除しない。"""
    record = States().public(race())
    assert record["x"].shape == (8, 9)
    assert np.array_equal(record["x"], np.zeros((8, 9)))
    assert np.array_equal(record["rel"], np.zeros((8, 9)))
    assert np.array_equal(pair_features(record, "ABC"), np.zeros((28, 22)))


def test_opponent_rating_uses_past_and_changes_only_after_update():
    """相手の結果を更新前に読むことなく、過去結果の反映後だけ評価が変わる。"""
    states = States()
    first = states.public(race(1))
    current = race(1)
    states.update_day([(current, {r["horse_no"]: 95 + i for i, r in enumerate(current["runners"])}, 1)])
    later = states.public(race(2))
    assert np.all(first["x"][:, 3] == 0)
    assert later["x"][0, 3] > later["x"][-1, 3]
    assert np.all((later["rel"] >= 0) & (later["rel"] <= 1))


def test_compact_legacy_history_exactly_matches_r1_columns():
    """省メモリの共通集計が、元R1の8入力列を履歴なし/更新後とも完全再現する。"""
    compact, original = States(), native.States()
    for i in range(5):
        current = race(i * 10 + 1)
        current.update(condition="703", late=.1)
        for j, runner in enumerate(current["runners"]):
            runner.update(age=3, weight=55, frame=j // 2 + 1, jockey="j", trainer="t", closing=34 + j)
        actual = compact.legacy_features(current)
        expected = residual.public_features(original, current)
        assert np.array_equal(actual[:, residual.BASIC], expected[:, residual.BASIC])
        compact.update_day([(current, {r["horse_no"]: 95 + j for j, r in enumerate(current["runners"])}, 1)])
        original.update(current)


def test_conditional_loss_gradient_matches_finite_difference():
    """可変競走ごとの正規化と解析勾配を数値微分で検証する。"""
    x = np.random.default_rng(226).normal(size=(9, 4)).astype(np.float32)
    starts, counts, targets = np.array([0, 3]), np.array([3, 6]), np.array([1, 8])
    beta = np.array([.1, -.2, .3, .4])
    value, gradient = objective(beta, x, starts, counts, targets, .01)
    numerical = []
    for i in range(4):
        delta = np.eye(4)[i] * 1e-6
        numerical.append((objective(beta + delta, x, starts, counts, targets, .01)[0]
                          - objective(beta - delta, x, starts, counts, targets, .01)[0]) / 2e-6)
    assert np.isfinite(value)
    assert np.allclose(gradient, numerical, rtol=1e-6, atol=1e-7)


def test_block_objective_matches_full_matrix_for_every_variant():
    """省メモリの逐次計算が全量行列版の尤度と勾配を全3構成で再現する。"""
    rng = np.random.default_rng(226)
    records = [{"x": rng.normal(size=(n, 9)), "rel": rng.uniform(size=(n, 9)), "quality": rng.uniform(size=(n, 2)),
                "race_date": "2024-01-01", "winner": i} for i, n in enumerate((4, 5, 8))]
    data = pack_training(records)
    for variant in ("A", "AB", "ABC"):
        horse_x = data["x"][:, :5] if variant == "A" else data["x"]
        if variant == "ABC":
            horse_x = np.column_stack((horse_x * data["rel"], data["quality"]))
        centers = centers_for(data, horse_x)
        x = np.concatenate([pair_features(r, variant) for r in records]).astype(np.float32)
        scale = np.maximum(np.sqrt(np.mean(x.astype(np.float64) ** 2, axis=0)), 1e-5)
        x /= scale.astype(np.float32)
        beta = rng.normal(size=x.shape[1])
        a, ga = objective(beta, x, data["starts"], data["counts"], data["targets"], .01)
        b, gb = packed_objective(beta, data, horse_x, centers, scale)
        assert np.isclose(a, b, rtol=1e-12) and np.allclose(ga, gb, rtol=1e-12, atol=1e-12)


def test_pair_distribution_is_normalized_and_horse_order_invariant():
    """馬連全組の合計と、馬番並べ替え後の対応する組の確率を確認する。"""
    rng = np.random.default_rng(226)
    record = {"x": rng.normal(size=(8, 9)), "rel": rng.uniform(size=(8, 9)), "quality": rng.uniform(size=(8, 2))}
    model = {"variant": "ABC", "scale": np.ones(22), "coef": rng.normal(size=22)}
    p = predict(model, record)
    order = np.array([7, 3, 1, 5, 0, 2, 6, 4])
    q = predict(model, {k: v[order] for k, v in record.items()})
    original = {tuple(pair): value for pair, value in zip(pairs(8), p, strict=True)}
    for pair, value in zip(pairs(8), q, strict=True):
        assert math.isclose(value, original[tuple(sorted(order[pair]))], rel_tol=1e-12)
    assert np.isclose(p.sum(), 1) and np.all(p > 0)


def test_toy_training_learns_joint_pair_target():
    """小規模合成データで尤度が一様予測を改善し、正しい馬連を上位にする。"""
    records = []
    for i in range(12):
        x = np.zeros((4, 9))
        x[:, 0] = [3, 2, -1, -2]
        records.append({"x": x, "rel": np.ones((4, 9)), "quality": np.ones((4, 2)), "race_date": "2024-01-01", "winner": 0})
    model = fit(records, "A")
    p = predict(model, records[0])
    assert np.argmax(p) == 0 and -np.log(p[0]) < math.log(6) / 2


def gate_fixture():
    """必要件数と開催日を満たす、同一T30比較の合成損失を作る。"""
    names = ("M0", "R1", "A", "AB", "ABC")
    return [{"race_date": f"2025-11-{i % 20 + 1:02d}",
             "loss": dict(zip(names, [3.5, 3.49, 3.6, 3.48, 3.45], strict=True)),
             "brier": {n: .02 for n in names}, "stake": {n: 0 for n in names}, "payout": {n: 0 for n in names}}
            for i in range(400)]


def test_shared_gate_compares_same_t30_baselines_and_stops_tiny_gain():
    """共有処理の比較名変換が時点変更を意味せず、小さい改善を拒否する。"""
    rows = gate_fixture()
    gate = accuracy_gate(rows, 400, "development")
    assert gate["passed"] and gate["all_variants_horizon"] == "T30"
    for r in rows:
        r["loss"]["ABC"] = 3.489
    assert not accuracy_gate(rows, 400, "development")["passed"]


def test_purchase_sample_is_separate_and_insufficient_is_not_passed():
    """精度が良くても購入標本のないモデルを採用しない。"""
    result = purchase_gate(gate_fixture(), [])
    assert result["status"] == "insufficient_sample" and result["intervals"] is None
