"""概要: D0除去列・学習後0・行列復元・結果/日付遮断を確認する。
作成日: 2026-10-25
入力: 人工8頭の公開特徴。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_d0_ablation.py
注意事項: 外部通信/旧学習/実購入なし。
"""

import numpy as np
import pytest

from jra_srb import jra_research_d0_ablation as model
from jra_srb.jra_research_contracts import ResearchError


def record():
    """15履歴と6属性を備えた人工競走を返す。"""
    rng = np.random.default_rng(405)
    return {'race_id': 'synthetic', 'race_date': '2020-01-01', 'course': 8, 'surface': 0, 'distance': 2000,
        'horses': [f'{v:02d}' for v in range(1, 9)], 'x': rng.normal(0, .1, (8, 15)).astype(np.float32),
        'attributes': np.tile([.3, 0, 0, .5, .5, 0], (8, 1)).astype(np.float32),
        'race_flags': np.zeros(3), 'market': np.full(28, 1/28), 'pl': np.full(28, 1/28), 'winner': 0}


def test_column_partition():
    """30履歴列と依存相互作用を重複なく除き、市場/属性を保持する。"""
    groups = [model.omitted_columns(b) for b in model.BLOCKS]
    assert sorted(v for g in groups for v in g) == list(range(2, 34))
    assert 32 in groups[0] and 33 in groups[3]
    with pytest.raises(ResearchError):
        model.omitted_columns('unknown')


def test_restoration_and_firewall():
    """除去再学習後に行列を復元し、0係数・公開入力だけの推論を保証する。"""
    r = record()
    train = [r, {**r, 'winner': 1}]
    packed = model.base.pack(train, 'D0')
    original = packed['x'].copy()
    fitted = model.fit_packed(packed, train, 'clock')
    np.testing.assert_array_equal(packed['x'], original)
    assert np.count_nonzero(fitted['coef'][:, model.omitted_columns('clock')]) == 0
    future = {**r, 'race_date': '2021-01-01'}
    np.testing.assert_array_equal(model.predict(fitted, future), model.predict(fitted, {**future, 'winner': -1, 'payout_yen': -1}))
    with pytest.raises(ResearchError):
        model.predict(fitted, r)


def test_restore_after_optimizer_failure(monkeypatch):
    """最適化途中で例外が出ても共有する訓練行列を汚さない。"""
    r = record()
    packed = model.base.pack([r], 'D0')
    original = packed['x'].copy()

    def fail(*args, **kwargs):
        """最適化失敗を模擬する。"""
        raise RuntimeError('synthetic optimizer failure')

    monkeypatch.setattr(model, 'minimize', fail)
    with pytest.raises(RuntimeError):
        model.fit_packed(packed, [r], 'rotation')
    np.testing.assert_array_equal(packed['x'], original)
