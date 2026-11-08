"""概要: 全馬連E選択の候補範囲・同点・見送りと期間判定を検証する。
作成日: 2026-11-07
入力: 合成確率/価格/精算。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_purchase_ev.py
注意事項: 外部通信・永続データ変更なし。
"""

import numpy as np
from jra_srb import jra_research_purchase_ev as ev


def test_selects_value_instead_of_probability():
    """確率最大とは異なる、候補中E最大の組を選ぶ。"""
    assert ev.select([.2, .1], [4., 15.], ev.policies()[0]) == 1


def test_rejects_extreme_price_and_small_probability():
    """大きな見かけEでも価格上限や確率下限の外を選ばない。"""
    assert ev.select([.02, .06, .10], [100., 21., 12.], ev.policies()[0]) == 2
    assert ev.select([.02, .06], [100., 21.], ev.policies()[0]) is None


def test_boundaries_tie_and_stricter_rules():
    """候補包含境界、E同点の先頭、3条件の違いを確認する。"""
    a, b, c = ev.policies()
    assert ev.select([.1, .1], [11., 11.], a) == 0
    assert ev.select([.1], [10.6], b) is None
    assert ev.select([.04], [20.], c) is None


def test_no_bets_or_no_results_do_not_pass():
    """未精算/購入0を黒字や有望と扱わない。"""
    a = ev.assess({'P01': []}, forward=True)['P01']
    assert a['total']['roi_percent'] is None and a['decision']['label'] == 'no_opportunities'


def test_nonfinite_prices_rejected():
    """無効価格の補完で選択を成立させない。"""
    import pytest
    with pytest.raises(ValueError):
        ev.select([.1], [np.nan], ev.policies()[0])
