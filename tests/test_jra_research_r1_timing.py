"""概要: R1研究の最小改善幅・終了ゲート・時点更新を検証する。
作成日: 2026-10-18
入力: 合成の競走別損失・確率・価格。外部接続なし。
出力: pytest検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_r1_timing.py
注意事項: SQL・API・実R1学習・実購入へ接続しない。
"""

import numpy as np

from jra_srb.jra_research_r1_timing import accuracy_gate, purchase_gate, score_market


def race_rows(count=400, days=20, r30=3.4, m10=3.39, r10=3.35):
    """同じ開催日に複数競走を持つ、損失差が一定の比較資料を作る。"""
    return [{"race_date": f"2025-11-{i % days + 1:02d}",
             "loss": {"M30": 3.41, "R30": r30, "M10": m10, "R10": r10},
             "brier": {v: .02 for v in ("M30", "R30", "M10", "R10")},
             "stake": {v: 0 for v in ("M30", "R30", "M10", "R10")},
             "payout": {v: 0 for v in ("M30", "R30", "M10", "R10")}} for i in range(count)]


def test_material_improvement_on_both_baselines_passes_screen():
    """両基準に対する実用改善幅と補正区間が揃えば一次通過する。"""
    result = accuracy_gate(race_rows(), 400, "development")
    assert result["passed"]
    assert result["vs_r30"]["relative_gain"] > .005
    assert result["vs_m10"]["difference_adjusted"][1] < 0


def test_tiny_but_certain_improvement_does_not_pass_materiality_gate():
    """統計上は改善方向でも最小改善幅に届かない案を継続しない。"""
    result = accuracy_gate(race_rows(r30=3.4, m10=3.4, r10=3.399), 400, "development")
    assert result["vs_r30"]["difference_adjusted"][1] < 0
    assert not result["checks"]["relative_gain_vs_r30"]
    assert not result["passed"]


def test_later_market_information_alone_is_not_r1_improvement():
    """T30より良くても同時点市場に負ける候補を不合格にする。"""
    result = accuracy_gate(race_rows(r30=3.5, m10=3.3, r10=3.35), 400, "development")
    assert result["checks"]["relative_gain_vs_r30"]
    assert not result["checks"]["relative_gain_vs_m10"]
    assert not result["passed"]


def test_missing_races_and_days_cannot_be_hidden_by_good_average():
    """少標本・低採用率は損失が良くても通過しない。"""
    result = accuracy_gate(race_rows(count=399, days=14), 500, "development")
    assert not result["checks"]["minimum_races"]
    assert not result["checks"]["minimum_days"]
    assert not result["checks"]["coverage"]
    assert not result["passed"]


def test_brier_worsening_blocks_promotion():
    """対数損失だけの改善で別の確率誤差が悪化する場合を拒否する。"""
    rows = race_rows()
    for r in rows:
        r["brier"]["R10"] = .021
    result = accuracy_gate(rows, 400, "development")
    assert not result["checks"]["brier_vs_r30"] and not result["passed"]


def test_t10_reinference_changes_probability_but_keeps_normalization():
    """時点価格を変えると市場とR1を更新し、固定確率の価格試算と区別する。"""
    x = np.random.default_rng(190).uniform(.1, 1, (8, 48))
    prices = np.linspace(4, 80, 28)
    model = {"variant": "R1", "scale": np.ones(17), "coef": np.linspace(-.1, .1, 17)}
    market30, p30 = score_market(model, x, prices)
    changed = prices.copy()
    changed[0] *= .8
    market10, p10 = score_market(model, x, changed)
    assert not np.allclose(market30, market10)
    assert not np.allclose(p30, p10)
    assert np.isclose(p10.sum(), 1)
    _, repeated = score_market(model, x, prices)
    assert np.array_equal(repeated, p30)


def test_zero_hit_small_sample_is_pending_not_adopted():
    """購入標本がない段階を不適切なゼロ幅区間や採用へ変換しない。"""
    result = purchase_gate(race_rows(), [])
    assert result["status"] == "insufficient_sample"
    assert result["intervals"] is None
    assert not result["checks"]["minimum_bets"]


def test_final_gate_requires_more_data_than_development():
    """開発通過の件数をそのまま最終検証の十分性と扱わない。"""
    assert accuracy_gate(race_rows(), 400, "development")["passed"]
    final = accuracy_gate(race_rows(), 400, "evaluation")
    assert not final["checks"]["minimum_races"]
    assert not final["checks"]["minimum_days"]
