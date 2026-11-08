"""概要: 順位追加損失の勾配・負例・市場混合・結果遮断を検査する。
作成日: 2026-10-24
入力: 固定seedの人工市場と公開特徴。
出力: pytest結果。
実行例: uv run --frozen --extra ml --extra dev pytest -q tests/test_jra_research_rank_chimera.py
注意事項: SQL/HTTP/実購入なし。人工一致を実性能とみなさない。
"""

import joblib
import numpy as np
import pytest

from jra_srb import jra_research_rank_chimera as m
from test_jra_research_market_chimera import records
from jra_srb.jra_research_contracts import ResearchError


def test_rank_gradient_and_zero_weight():
    """順位損失の勾配を数値差分、係数0時の旧CEを既存式と照合する。"""
    data = m.prepare_rank_data(records(105), .5)
    b = np.random.default_rng(360).normal(0, .02, len(data['names'])*data['x'].shape[1])
    analytic = m.objective(b, data)[1]
    for i in np.linspace(0, len(b)-1, 12, dtype=int):
        e = np.zeros_like(b)
        e[i] = 1e-5
        numeric = (m.objective(b+e, data)[0]-m.objective(b-e, data)[0])/2e-5
        assert analytic[i] == pytest.approx(numeric, abs=1e-7)
    data['rank_weights'][:] = 0
    old_loss, old_gradient = m.core.objective(b, data)
    loss, gradient = m.objective(b, data)
    assert loss == pytest.approx(old_loss, abs=1e-12)
    np.testing.assert_allclose(gradient, old_gradient, atol=1e-12)


def test_negatives_are_market_top_five_and_exclude_winner():
    """正解を負例に混ぜず、市場上位の整数位置だけを選ぶ。"""
    rows = records(10)
    data = m.prepare_rank_data(rows, .25)
    for r, start, target in zip(rows, data['starts'], data['targets']):
        selected = data['negative'][data['positive'] == target]-start
        assert int(r['winner']) not in selected
        assert set(selected) == set(np.argsort(-r['market'])[:5])-{r['winner']}
    assert data['rank_weights'].sum() == pytest.approx(.25)


@pytest.mark.parametrize('case', list(m.RANK_WEIGHTS))
def test_rank_model_save_results_and_time(case, tmp_path):
    """保存後一致と結果遮断、訓練日以後という推論制約を検査する。"""
    rows = records(20)
    fitted = m.fit(rows, case)
    path = tmp_path/f'{case}.joblib'
    joblib.dump(fitted, path)
    r = {**rows[0], 'race_date': '2023-01-01'}
    p = m.predict(fitted, r)
    np.testing.assert_array_equal(p, m.predict(joblib.load(path), {**r, 'winner': -1, 'payout_yen': -999}))
    assert min(p) > 0 and p.sum() == pytest.approx(1)
    with pytest.raises(ResearchError, match='market_chimera_future_training'):
        m.predict(fitted, rows[0])


def test_convex_mix_is_exact_and_rank_wrapper_does_not_train():
    """G50を基準H2と市場の厳密な半分混合として確認する。"""
    rows = records(20)
    fitted = m.core.fit(rows, 'H2')
    r = {**rows[0], 'race_date': '2023-01-01'}
    p = m.core.predict(fitted, r)
    np.testing.assert_array_equal(m.predict(m.wrap(fitted, 'H2'), r), p)
    np.testing.assert_array_equal(m.predict(m.wrap(fitted, 'G50'), r), .5*p+.5*r['market'])
