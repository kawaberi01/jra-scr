"""概要: 競馬場別D0の教師混入拒否・別場拒否・日付・保存一致を確認する。
作成日: 2026-10-25
入力: 小規模な人工D0公開特徴。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_course_chimera.py
注意事項: SQL/HTTP/本番モデル更新なし。
"""

import joblib
import numpy as np
import pytest

from jra_srb import jra_research_course_chimera as model
from jra_srb.jra_research_contracts import ResearchError


def record(day='2020-01-01', course=8):
    """場と日付を変更できる人工8頭競走を返す。"""
    rng = np.random.default_rng(395)
    return {'race_id': day, 'race_date': day, 'course': course, 'surface': 0, 'distance': 2000,
        'horses': [f'{v:02d}' for v in range(1, 9)], 'x': rng.normal(0, .1, (8, 15)).astype(np.float32),
        'attributes': np.tile([.3, 0, 0, .5, .5, 0], (8, 1)).astype(np.float32), 'race_flags': np.zeros(3),
        'market': np.full(28, 1/28), 'pl': np.full(28, 1/28), 'winner': 0}


def test_training_scope():
    """教師の他場混入と空入力を拒否する。"""
    with pytest.raises(ResearchError):
        model.fit([record(), record(course=5)], 8)
    with pytest.raises(ResearchError):
        model.fit([], 8)


def test_prediction_scope_reload_and_dates(tmp_path):
    """場境界・日付境界・保存・結果遮断と既存D0推論の一致を確認する。"""
    r = record()
    fitted = model.fit([r, {**r, 'race_date': '2020-01-02', 'winner': 1}], 8)
    assert fitted['trained_course'] == 8 and fitted['train_races'] == 2
    future = {**r, 'race_date': '2021-01-01'}
    p = model.predict(fitted, future)
    np.testing.assert_array_equal(p, model.base.predict(fitted, future))
    joblib.dump(fitted, tmp_path/'course.joblib')
    np.testing.assert_array_equal(p, model.predict(joblib.load(tmp_path/'course.joblib'), {**future, 'winner': -1, 'payout_yen': -1}))
    with pytest.raises(ResearchError):
        model.predict(fitted, {**future, 'course': 5})
    with pytest.raises(ResearchError):
        model.predict(fitted, r)
