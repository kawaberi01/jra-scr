"""概要: S1の独立検算で検出した中心化縮約順によるfloat32差を再現する。
作成日: 2026-10-27
入力: 固定済みS1特徴と2025モデル、実際に差が出た202501180712。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_s1_rounding_contract.py
注意事項: 読取だけ。学習・SQL・HTTP・係数変更なし。
"""

import importlib

import joblib
import numpy as np

from jra_srb import jra_research_recent_current as model
from jra_srb.jra_research_artifacts import ROOT


def test_dot_cast_boundaries_reproduce_saved_features(monkeypatch):
    """sum縮約の微差を再現し、内積/丸め契約で厳密一致することを確認する。"""
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    old = importlib.import_module('verify_jra_recent_current')
    fixed = importlib.import_module('verify_jra_recent_current_v2')
    folder = ROOT/'artifacts/jra_research/recent_current_S1_20261027'
    data = joblib.load(folder/'dataset.joblib')
    record = next(r for r in data['records'] if r['race_id'] == '202501180712')
    expected = model.matrix(record)
    sum_matrix = old.independent_matrix(record)
    assert np.max(np.abs(expected-sum_matrix)) <= 1e-8
    np.testing.assert_array_equal(expected, fixed.independent_matrix(record))
    fitted = joblib.load(folder/'2025_S1.joblib')
    a, b = model.predict(fitted, record), old.independent_predict(fitted, record)
    assert np.max(np.abs(a-b)) <= 1e-10 and np.argmax(a) == np.argmax(b)
