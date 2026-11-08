"""概要: 20仮説の時点分離・PL尤度・入力条件・固定選抜を検証する。
作成日: 2026-10-18
入力: 合成の履歴・市場・競走別損失。SQL接続なし。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_chimera_twenty.py
注意事項: 実データの学習・モデル採用は行わない。
"""

from copy import deepcopy
from itertools import combinations
import json
import math

import numpy as np
import pytest

from jra_srb import jra_research_chimera as old
from jra_srb import jra_research_chimera_twenty as plan
from jra_srb import jra_research_chimera_twenty_fit as research
from jra_srb.jra_research_contracts import ResearchError


def race(day=10):
    """過去ラップと個別上がりを区別した8頭の合成競走を作る。"""
    return {"ordinal": day, "day": "2024-01-10", "surface": 0, "distance": 1600, "course": 5,
            "pace": -.8, "closing_total": 35.5,
            "runners": [{"horse_id": str(i), "horse_no": f"{i + 1:02d}", "rank": i + 1,
                         "corner": i + 1, "age": 3, "closing": 34.5 + i / 10} for i in range(8)]}


def records():
    """頭数の異なる小規模行列で、学習と勾配照合に必要な教師を用意する。"""
    rng = np.random.default_rng(232)
    return [{"x": rng.normal(size=(n, 9)).astype(np.float32),
             "extra": rng.uniform(size=(n, 27)).astype(np.float32),
             "winner": i, "race_date": "2024-01-01"} for i, n in enumerate((4, 6, 8))]


def test_coverage_boundary_and_time_splits():
    """95%の境界を許可し、片方不足なら学習を許可しない。"""
    rows = [{"race_date": day, "split": split, "valid": i < 19, "reason": None if i < 19 else "missing_T30"}
            for split, day in (("primary", "2025-06-30"), ("secondary", "2025-07-01")) for i in range(20)]
    assert plan.coverage_summary(rows)["passed"]
    rows[0].update(valid=False, reason="missing_T30")
    assert not plan.coverage_summary(rows)["passed"]
    assert plan.split_for("2025-06-30") == "primary"
    assert plan.split_for("2025-07-01") == "secondary"
    assert plan.split_for("2025-10-01") is None
    assert len(set(plan.CASES)) == 20


def test_input_rejects_missing_future_market_and_wrong_HR():
    """完全ペア市場だけを許し、欠測・未来公表・誤払戻を拒否する。"""
    current = race()
    entries = [{"market": "quinella", "selection_key": a + b, "odds_status_low": "numeric", "odds_low_x10": 100}
               for a, b in combinations([r["horse_no"] for r in current["runners"]], 2)]
    market = {"horizon": "T30", "market": "quinella", "selection_status": "selected", "parser_version": "jv-o1o2-v2",
              "content_sha256": "a" * 64, "announced_at": "2025-01-01T10:00:00+09:00",
              "cutoff_at": "2025-01-01T10:10:00+09:00", "entries_json": json.dumps(entries)}
    hr = {"market": "quinella", "slot_status": "published", "hr_sha256": "b" * 64,
          "selection_raw": "0102", "payout_yen": 1000, "payout_raw": "00001000"}
    assert len(plan.validate_inputs(current, [market], [hr])) == 28
    for markets, payouts in (([], [hr]), ([{**market, "announced_at": "2025-01-01T10:11:00+09:00"}], [hr]),
                              ([market], [{**hr, "selection_raw": "0103"}])):
        with pytest.raises(ResearchError):
            plan.validate_inputs(current, markets, payouts)


def test_extended_state_matches_N0_and_ignores_current_results():
    """追加集計がN0の定義を変えず、現在の着順や実ペースに依存しない。"""
    state, control = research.TwentyStates(), old.States()
    for day in (1, 5, 12):
        current = race(day)
        expected = control.public(current)["x"].astype(np.float32)
        assert np.array_equal(state.public(current)["x"], expected)
        polluted = deepcopy(current)
        polluted.update(pace=1000, closing_total=1)
        for runner in polluted["runners"]:
            runner.update(rank=99, corner=99, closing=1)
        for key, value in state.public(current).items():
            assert np.array_equal(value, state.public(polluted)[key])
        updates = [(current, {r["horse_no"]: 95 + i for i, r in enumerate(current["runners"])}, 1)]
        state.update_day(updates)
        control.update_day(updates)
    with pytest.raises(ResearchError):
        state.public(race(12))


def test_every_case_has_finite_features_and_training_only_knots():
    """全20IDの入力変換が有限で、折れ線節点を未指定のまま推論しない。"""
    record = records()[0]
    for case in plan.CASES:
        x = research.horse_features(record["x"], record["extra"], case, np.array([-.5, 0, .5]))
        assert len(x) == 4 and np.isfinite(x).all()
    with pytest.raises(ResearchError):
        research.horse_features(record["x"], record["extra"], "H07")


def test_PL_analytic_gradient_matches_finite_difference():
    """順序を合算した馬連尤度の解析勾配を独立な数値差分へ照合する。"""
    data = research.pack(records())
    x = data["x"].astype(float)
    beta = np.linspace(-.15, .2, 9)
    value, gradient = research.pl_objective(beta, x, data)
    numerical = []
    for i in range(9):
        delta = np.eye(9)[i] * 1e-6
        numerical.append((research.pl_objective(beta + delta, x, data)[0]
                          - research.pl_objective(beta - delta, x, data)[0]) / 2e-6)
    assert np.isfinite(value) and np.allclose(gradient, numerical, rtol=1e-6, atol=1e-7)


@pytest.mark.parametrize("case", ["N0", "H17"])
def test_pair_blocks_match_independent_full_likelihood(case):
    """共通/積項ペアの省メモリ尤度を全量行列の尤度・勾配へ照合する。"""
    inputs = records()
    data = research.pack(inputs)
    x = research.horse_features(data["x"], data["extra"], case)
    dimension = x.shape[1] * 2 + (2 if case == "H17" else 0)
    full = np.concatenate([research.local_pairs(research.horse_features(r["x"], r["extra"], case), r["extra"], case) for r in inputs]).astype(np.float32)
    centers = []
    for r in inputs:
        hx = research.horse_features(r["x"], r["extra"], case)
        indices = old.pairs(len(hx))
        a, b = hx[indices[:, 0]].astype(float), hx[indices[:, 1]].astype(float)
        values = np.column_stack(((a + b) / 2, np.abs(a - b)))
        if case == "H17":
            values = np.column_stack((values, a[:, 0] * b[:, 0],
                (a[:, 0] * r["extra"][indices[:, 1], 24] + b[:, 0] * r["extra"][indices[:, 0], 24]) / 2))
        centers.append(values.mean(axis=0))
    scale = np.maximum(np.sqrt(np.mean(full.astype(float) ** 2, axis=0)), 1e-5)
    full /= scale.astype(np.float32)
    beta = np.linspace(-.2, .2, dimension)
    loss, gradient = research.pair_objective(beta, data, x, np.asarray(centers), scale, case)
    expected, eg = old.objective(beta, full, data["starts"], data["counts"], data["targets"], .01)
    assert np.isclose(loss, expected, rtol=1e-12) and np.allclose(gradient, eg, rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize("case", ["H01", "H07", "H17", "H18"])
def test_fit_normalization_order_invariance_and_result_independence(case):
    """学習済み分布の総和1・馬順対応・結果非依存を複数の確率モデルで確認する。"""
    inputs = records()
    model = research.fit(research.pack(inputs), case)
    record = inputs[2]
    p = research.predict(model, record)
    assert np.all(p > 0) and np.isclose(p.sum(), 1)
    assert np.array_equal(p, research.predict(model, {"x": record["x"], "extra": record["extra"]}))
    order = np.array([7, 2, 0, 5, 3, 4, 6, 1])
    q = research.predict(model, {"x": record["x"][order], "extra": record["extra"][order]})
    original = {tuple(pair): value for pair, value in zip(old.pairs(8), p, strict=True)}
    for pair, value in zip(old.pairs(8), q, strict=True):
        assert math.isclose(value, original[tuple(sorted(order[pair]))], rel_tol=1e-7, abs_tol=1e-9)


def test_secondary_rejects_improvement_only_against_weak_control():
    """弱いN0より良くても市場未達なら候補採用しない。"""
    primary = {"H19": {"logloss": 3.6}, "M0": {"logloss": 3.4}}
    secondary = {"H19": {"logloss": 3.5, "brier": .02}, "M0": {"logloss": 3.4, "brier": .02},
                 "N0": {"logloss": 4.0, "brier": .03}}
    result = research.secondary_decision(primary, secondary, ["H19"])
    assert result["selected"] is None and not result["checks"]["H19"]["passed"]
    primary["H19"]["logloss"] = 3.3
    secondary["H19"]["logloss"] = 3.3
    assert research.secondary_decision(primary, secondary, ["H19"])["selected"] == "H19"


def test_fixed_mixtures_normalize_without_weight_selection():
    """固定算術/幾何混合を手計算へ照合し、重み探索を含まない。"""
    p, market = np.array([.8, .2]), np.array([.3, .7])
    assert np.allclose(research.mix(p, market, "H19"), [.35, .65])
    expected = market ** .9 * p ** .1
    expected /= expected.sum()
    assert np.allclose(research.mix(p, market, "H20"), expected)


def test_shared_training_keeps_identical_inputs_without_copying_features():
    """共有view版が従来連結版と同じ入力・尤度を作り、特徴を複製しない。"""
    inputs = records()
    original = research.pack(inputs)
    flat_x, flat_extra = np.concatenate([r["x"] for r in inputs]), np.concatenate([r["extra"] for r in inputs])
    offset, shared = 0, []
    for record in inputs:
        count = len(record["x"])
        shared.append({**record, "x": flat_x[offset:offset + count], "extra": flat_extra[offset:offset + count], "_offset": offset})
        offset += count
    data = research.pack(shared)
    assert np.shares_memory(data["x"], flat_x) and np.shares_memory(data["extra"], flat_extra)
    for key in ("x", "extra", "left", "right", "counts", "starts", "targets", "group", "horse_starts", "horse_group"):
        assert np.array_equal(data[key], original[key])
    beta = np.linspace(-.1, .1, 9)
    a, ga = research.pl_objective(beta, original["x"].astype(float), original)
    b, gb = research.pl_objective(beta, data["x"].astype(float), data)
    assert a == b and np.array_equal(ga, gb)


def test_compact_R1_columns_reproduce_full_matrix_in_actual_evaluation():
    """実評価経路で8列から復元したR1が元48列の確率を完全再現する。"""
    rng = np.random.default_rng(232)
    current = race()
    full = rng.normal(size=(8, 48))
    model = {"variant": "R1", "scale": np.ones(17), "coef": rng.normal(size=17) / 10}
    market = np.full(28, 1 / 28)
    expected = old.residual.predict(model, {"x": full, "market": market})
    record = {"race_key": "202501010501", "race_date": "2025-01-01", "winner": 0, "race": current,
              "x": np.zeros((8, 9), np.float32), "extra": np.zeros((8, 27), np.float32),
              "legacy_x": full[:, old.residual.BASIC].copy()}
    prices = {record["race_key"]: {"prices": np.full(28, 20.0), "market": market, "payout_yen": 1000,
        "pairs": list(combinations([r["horse_no"] for r in current["runners"]], 2)),
        "market_sha256": "a" * 64, "hr_sha256": "b" * 64}}
    rows, _, _ = research.evaluate([record], {}, prices, "development", model)
    assert rows[0]["moments"]["R1"]["winning_probability"] == expected[0]
    assert rows[0]["moments"]["R1"]["squared_sum"] == float(expected @ expected)
