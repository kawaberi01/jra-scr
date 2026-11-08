"""概要: 市場基準キメラの勾配、結果遮断、対照再現、保存と時系列制約を検査する。
作成日: 2026-10-24
入力: 固定seedの人工市場と過去特徴。
出力: pytest結果。
実行例: uv run --frozen --extra ml --extra dev pytest -q tests/test_jra_research_market_chimera.py
注意事項: SQL/HTTP/実購入なし。人工データは予測性能の証明ではない。
"""

import joblib
import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative
from scipy.special import softmax

from jra_srb import jra_research_market_chimera as m
from jra_srb.jra_research_contracts import ResearchError


def records(n=105):
    """有限で完全な馬連市場と能力特徴を含む人工教師を作る。"""
    rng = np.random.default_rng(355)
    out = []
    for i in range(n):
        q = softmax(rng.normal(size=28))
        pl = softmax(np.log(q)+rng.normal(0, .1, size=28))
        out.append({'race_id': str(i), 'race_date': '2022-01-01', 'course': 8, 'surface': 0,
            'distance': 3000, 'horses': [str(j) for j in range(1, 9)], 'x': rng.normal(size=(8, 15)).astype(np.float32),
            'market': q, 'pl': pl, 'winner': int(rng.choice(28, p=q))})
    return out


def test_gradient_including_offset_and_context():
    """条件差分を含む非0係数の解析勾配を独立数値差分で照合する。"""
    data = m.pack(records(), 'H2')
    b = np.random.default_rng(3).normal(0, .02, len(data['names'])*data['x'].shape[1])
    gradient = m.objective(b, data)[1]
    for index in np.linspace(0, len(b)-1, 12, dtype=int):
        epsilon = np.zeros_like(b)
        epsilon[index] = 1e-5
        numeric = (m.objective(b+epsilon, data)[0]-m.objective(b-epsilon, data)[0])/2e-5
        assert gradient[index] == pytest.approx(numeric, abs=1e-7)


@pytest.mark.parametrize('case', m.CASES)
def test_model_serialization_and_outcome_firewall(case, tmp_path):
    """各方式の保存後推論、正規化、結果遮断と時点境界を確認する。"""
    rows = records(20)
    fitted = m.fit(rows, case)
    path = tmp_path/f'{case}.joblib'
    joblib.dump(fitted, path)
    r = {**rows[0], 'race_date': '2023-01-01'}
    p = m.predict(fitted, r)
    np.testing.assert_array_equal(p, m.predict(joblib.load(path), {**r, 'winner': -1, 'payout_yen': 99999}))
    assert p.sum() == pytest.approx(1) and min(p) > 0
    with pytest.raises(ResearchError, match='market_chimera_future_training'):
        m.predict(fitted, rows[0])


def test_zero_correction_reproduces_market():
    """補正係数0なら全市場分布を再現し、人気順の取り違えがないことを確認する。"""
    rows = records(20)
    fitted = m.fit(rows, 'H2')
    fitted['coef'][:] = 0
    r = {**rows[0], 'race_date': '2023-01-01'}
    np.testing.assert_allclose(m.predict(fitted, r), r['market'], atol=1e-15)


def test_incomplete_market_rejected():
    """不足した市場ペアを推測で埋めず拒否する。"""
    r = records(1)[0]
    with pytest.raises(ResearchError, match='market_chimera_market_contract'):
        m.matrix({**r, 'market': r['market'][:-1]}, 'P0')
