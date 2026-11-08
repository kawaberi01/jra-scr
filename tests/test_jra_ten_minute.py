"""概要: M10市場変化の中心化・結果遮断・入力名簿を検証する。
作成日: 2026-11-07
入力: 8頭の合成市場/属性。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_ten_minute.py
注意事項: 学習・外部通信・永続変更なし。
"""

import numpy as np
import pytest
from jra_srb import jra_research_ten_minute as model


def record():
    """実市場と同じ形状の8頭28組を作る。"""
    q = np.arange(1, 29, dtype=float); q /= q.sum()
    return {'race_id': '202601040601', 'race_date': '2026-01-04', 'course': 6, 'surface': 0,
            'distance': 1600, 'horses': [f'{i:02d}' for i in range(1, 9)],
            'market': q, 'pl': q.copy(), 'early_market': q.copy(), 'early_pl': q.copy(),
            'attributes': np.array([[.3, 0, 0, (i + 1) / 8, (i + 1) / 8, 0] for i in range(8)], dtype=np.float32)}


def test_zero_change_is_zero_and_s0_columns_unchanged():
    """市場不変なら追加2列は0、既存14列は完全に一致する。"""
    r = record(); x = model.matrix(r)
    assert x.shape == (28, 16)
    assert np.array_equal(x[:, :14], model.base.matrix(r))
    assert np.array_equal(x[:, 14:], np.zeros((28, 2), dtype=np.float32))


def test_movement_is_centered_on_late_market():
    """変化列はT10の市場期待値0で、T30で中心化しない。"""
    r = record(); r['early_market'] = r['early_market'][::-1].copy()
    assert np.max(np.abs(r['market'] @ model.movement(r))) < 1e-7
    assert np.max(np.abs(model.movement(r))) > .1


def test_features_ignore_winner_payout_and_history():
    """正解・払戻・時刻後の価格を加えても特徴を変えない。"""
    r = record()
    assert np.array_equal(model.matrix(r), model.matrix(r | {'winner': 20, 'payout_yen': 99999, 'final_odds': [999]}))


def test_bad_early_roster_rejected():
    """早い時点の不完全市場を補完せず拒否する。"""
    r = record(); r['early_market'] = np.ones(5)
    with pytest.raises(ValueError):
        model.movement(r)
