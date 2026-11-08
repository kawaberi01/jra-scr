"""概要: 信頼度相互作用の境界・勾配・保存・結果遮断を検査する。
作成日: 2026-10-24
入力: 人工公開特徴と小規模な人工教師。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_quality_chimera.py
注意事項: SQL/HTTP/本番モデル更新なし。
"""

import joblib
import numpy as np
import pytest

from jra_srb import jra_research_quality_chimera as model
from jra_srb.jra_research_contracts import ResearchError


def record(day='2020-01-01'):
    """公開欄と正解を区別できる8頭の人工競走を作る。"""
    rng = np.random.default_rng(370)
    x = rng.normal(0, .1, (8, 15)).astype(np.float32)
    x[:, 9] = np.log1p(5)/5
    x[:, 10] = 90/365
    x[:, 12] = 2
    x[:, 13] = 0
    x[:, 11] = 0
    return {'race_id': day, 'race_date': day, 'course': 8, 'surface': 0, 'distance': 3000,
        'horses': [f'{i:02d}' for i in range(1, 9)], 'x': x, 'market': np.full(28, 1/28), 'pl': np.full(28, 1/28),
        'attributes': np.tile([.3, 0, 0, .5, .5, 0], (8, 1)).astype(np.float32), 'race_flags': np.zeros(3), 'winner': 0}


def test_gate_boundaries():
    """過去件数・休養・条件変更の尺度とゼロ境界を検査する。"""
    r = record()
    np.testing.assert_allclose(model.gate(r, 'QH'), .5, atol=1e-7)
    np.testing.assert_allclose(model.gate(r, 'QR'), .5, atol=1e-7)
    np.testing.assert_allclose(model.gate(r, 'QC'), np.exp(-1))
    r['x'][:, [9, 10, 12]] = 0
    assert np.all(model.gate(r, 'QH') == 0)
    assert np.all(model.gate(r, 'QR') == 1)
    assert np.all(model.gate(r, 'QC') == 1)
    r['x'][:, 13] = 1
    assert np.all(model.gate(r, 'QC') == 0)
    r['x'][0, 9] = -1
    with pytest.raises(ResearchError):
        model.gate(r, 'QH')


@pytest.mark.parametrize('case', model.CASES)
def test_shapes_reload_firewall_and_date(case, tmp_path):
    """64列・保存一致・結果非依存・教師日付境界を確認する。"""
    r = record()
    x = model.matrix(model.clean(r), case)
    assert x.shape == (28, 64) and x.dtype == np.float32
    fitted = model.fit([r, {**r, 'race_date': '2020-01-02', 'winner': 1}], case)
    future = {**r, 'race_date': '2021-01-01'}
    p = model.predict(fitted, future)
    joblib.dump(fitted, tmp_path/'model.joblib')
    np.testing.assert_array_equal(p, model.predict(joblib.load(tmp_path/'model.joblib'), {**future, 'winner': -1, 'payout_yen': -1}))
    with pytest.raises(ResearchError):
        model.predict(fitted, r)


def test_added_gradient():
    """追加64列に対する損失の解析勾配を有限差分と照合する。"""
    r = record()
    data = model.base.core.pack([r], 'H2')
    data['x'] = model.matrix(r, 'QR')
    beta = np.linspace(-.02, .02, 64)
    _, gradient = model.base.core.objective(beta, data)
    for i in (0, 34, 46, 63):
        direction = np.zeros(64)
        direction[i] = 1e-6
        numerical = (model.base.core.objective(beta+direction, data)[0]-model.base.core.objective(beta-direction, data)[0])/2e-6
        assert gradient[i] == pytest.approx(numerical, abs=1e-7)
