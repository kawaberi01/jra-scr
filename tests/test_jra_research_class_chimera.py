"""概要: 競走条件コードの欠測・最小件数・日付・結果遮断を確認する。
作成日: 2026-10-25
入力: 人工8頭競走。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_class_chimera.py
注意事項: SQL/HTTP/既定変更なし。
"""

import joblib
import numpy as np
import pytest

from jra_srb import jra_research_class_chimera as model
from jra_srb.jra_research_contracts import ResearchError


def record():
    """条件コード付きの人工D0公開特徴を返す。"""
    rng = np.random.default_rng(400)
    return {'race_id': 'synthetic', 'race_date': '2020-01-01', 'course': 8, 'surface': 0, 'distance': 2000,
        'class_code': '703', 'horses': [f'{v:02d}' for v in range(1, 9)],
        'x': rng.normal(0, .1, (8, 15)).astype(np.float32),
        'attributes': np.tile([.3, 0, 0, .5, .5, 0], (8, 1)).astype(np.float32),
        'race_flags': np.zeros(3), 'market': np.full(28, 1/28), 'pl': np.full(28, 1/28), 'winner': 0}


def test_code_and_training_threshold():
    """コードを順序尺度にせず、100件未満と未設定に差分係数を作らない。"""
    assert [model.normalize_code(v) for v in (None, '', '000', '70', ' 703 ', '005')] == ['UNK', 'UNK', 'UNK', 'UNK', '703', '005']
    r = record()
    assert 'class:703' not in model.pack([r]*99)[0]['names']
    data, counts = model.pack([r]*100+[{**r, 'class_code': '000'}]*100)
    assert counts == {'703': 100, 'UNK': 100}
    assert 'class:703' in data['names'] and 'class:UNK' not in data['names']
    assert len(data['indices'][data['names'].index('class:703')]) == 2800


def test_reload_firewall_and_unknown(tmp_path):
    """保存一致・未知コードの共有復帰・日付と結果遮断を確認する。"""
    r = record()
    fitted = model.fit([r, {**r, 'winner': 1}])
    future = {**r, 'race_date': '2021-01-01'}
    p = model.predict(fitted, future)
    np.testing.assert_array_equal(p, model.predict(fitted, {**future, 'class_code': None}))
    joblib.dump(fitted, tmp_path/'class.joblib')
    np.testing.assert_array_equal(p, model.predict(joblib.load(tmp_path/'class.joblib'), {**future, 'winner': -1, 'payout_yen': -1}))
    with pytest.raises(ResearchError):
        model.predict(fitted, r)
