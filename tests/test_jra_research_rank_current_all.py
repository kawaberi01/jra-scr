"""概要: 有力負例だけの偏りと、S2B全負例の重み・勾配・スコア契約を確認する。
作成日: 2026-11-05
入力: 人工の真の市場、保存原本1件、合成教師。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_rank_current_all.py
注意事項: 読取・純計算だけ。実学習・SQL・HTTPなし。
"""

import numpy as np
import pytest

from jra_srb import jra_research_rank_current_all as model
from test_jra_research_rank_current import record, fitted


def expected_gradient(q, top_only):
    """真の市場から生成される正例を全列挙し、期待スコア勾配を求める。"""
    score, gradient = np.log(q), np.zeros(len(q))
    for winner in range(len(q)):
        negatives = [i for i in (range(5) if top_only else range(len(q))) if i != winner]
        for i in negatives:
            d = q[winner]/len(negatives)/(1+np.exp(-(score[i]-score[winner])))
            gradient[i] += d
            gradient[winner] -= d
    return gradient


def test_top_only_bias_even_with_true_market_and_all_negative_cancellation():
    """市場が正しくても上位外が正例だけになる偏りと、全負例での相殺を確認する。"""
    q = np.arange(1, 29, dtype=float)**-1.5
    q /= q.sum()
    assert np.all(expected_gradient(q, True)[5:] < 0)
    np.testing.assert_allclose(expected_gradient(q, False), 0, atol=1e-14)


def test_all_negative_coverage_and_equal_race_weights():
    """各競走で正解以外の全組を比較し、競走重みの和を同じに保つ。"""
    r = record()
    records = [r|{'winner': 0}, r|{'winner': len(r['market'])-1}]
    data = model.pack(records)
    n = len(r['market'])-1
    assert len(data['x']) == n*2
    assert data['weights'][:n].sum() == pytest.approx(.5) and data['weights'][n:].sum() == pytest.approx(.5)
    base = model.base.pack(records)
    assert np.array_equal(data['scale'], base['scale']) and data['names'] == base['names']
    expected = base['x'][1:n+1].astype(float)-base['x'][0].astype(float)
    np.testing.assert_array_equal(data['x'][:n], expected)


def test_all_negative_context_gradient():
    """全負例と条件差分の目的関数の解析勾配を数値差分で確認する。"""
    r = record()
    data = model.pack([r|{'winner': i % len(r['market'])} for i in range(100)])
    beta = np.linspace(-.02, .02, len(data['names'])*14)
    analytic = model.previous.objective(beta, data)[1]
    for i in [0, 13, 14, len(beta)-1]:
        delta = np.zeros_like(beta)
        delta[i] = 1e-5
        numeric = (model.previous.objective(beta+delta, data)[0]-model.previous.objective(beta-delta, data)[0])/2e-5
        assert analytic[i] == pytest.approx(numeric, abs=1e-7)


def test_shared_score_contract_with_explicit_variant():
    """訓練variantを明記しても14列の推論契約は変えない。"""
    r = record()
    f = fitted()|{'case': 'S2B', 'negative_top': 'all', 'training_protocol': model.TRAINING_PROTOCOL}
    np.testing.assert_array_equal(model.scores(f, r), model.previous.scores(f, r))
