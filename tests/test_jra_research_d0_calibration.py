"""概要: D0出力校正の恒等/端点/境界/保存/結果遮断を確認する。
作成日: 2026-10-25
入力: 人工の正規化済み28ペア確率。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_d0_calibration.py
注意事項: SQL/HTTP/D0再学習なし。
"""

import json

import numpy as np
import pytest

from jra_srb import jra_research_d0_calibration as model
from jra_srb.jra_research_contracts import ResearchError


def record(day='2023-01-01'):
    """学習境界を確認できる人工競走を作る。"""
    p = np.arange(1, 29, dtype=float)
    p /= p.sum()
    return {'race_id': day, 'race_date': day, 'p': p, 'q': np.full(28, 1/28), 'winner': 27}


def test_identities_and_limits():
    """恒等・市場への端点と温度の順位不変性を確認する。"""
    r = record()
    for case, parameters in [('K0', {}), ('KT', {'t': 1}), ('KR', {'a': 1}), ('KC', {'high': 1, 'low': 1}), ('KM', {'e': 0})]:
        np.testing.assert_allclose(model.transform(case, parameters, r), r['p'], atol=1e-15)
    np.testing.assert_allclose(model.transform('KR', {'a': 0}, r), r['q'], atol=1e-15)
    assert np.argmax(model.transform('KT', {'t': .7}, r)) == np.argmax(r['p'])
    assert np.argmax(model.transform('KT', {'t': 1.3}, r)) == np.argmax(r['p'])
    r['q'][0] = 0
    with pytest.raises(ResearchError):
        model.transform('KR', {'a': .5}, r)


@pytest.mark.parametrize('case', model.CASES)
def test_fit_reload_dates_and_result(case):
    """期間分離、校正係数のJSON保存、結果非依存を確認する。"""
    r = record()
    fitted = model.fit([r, {**r, 'race_id': 'second', 'race_date': '2023-08-31', 'winner': 0}], case)
    restored = json.loads(json.dumps(fitted))
    future = {**r, 'race_date': '2023-09-01'}
    np.testing.assert_array_equal(model.predict(fitted, future), model.predict(restored, {**future, 'winner': -1, 'payout_yen': -1}))
    assert fitted['train_races'] == 2 and fitted['trained_through'] == '2023-08-31'
    with pytest.raises(ResearchError):
        model.fit([future], case)
    with pytest.raises(ResearchError):
        model.predict(fitted, r)


def test_confidence_bucket():
    """KCの分岐が結果ではなく公開最大確率0.2で決まることを確認する。"""
    r = record()
    parameters = {'high': 0, 'low': 1}
    np.testing.assert_allclose(model.transform('KC', parameters, r), r['p'])
    r['p'] = np.full(28, .8/27)
    r['p'][0] = .2
    np.testing.assert_allclose(model.transform('KC', parameters, r), r['q'])
