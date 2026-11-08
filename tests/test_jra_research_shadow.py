"""概要: 発走前時刻の強制と、仮想100円/実購入0円の分離を検証する。
作成日: 2026-11-07
入力: 合成の8頭市場と時刻。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_shadow.py
注意事項: SQL/HTTP/実購入なし。
"""

from datetime import datetime, timedelta, timezone
import numpy as np
import pytest
from jra_srb import jra_research_shadow as shadow


def inputs():
    """8頭28組の有限な確率と実価格を返す。"""
    r = {'race_id': '202611070501', 'horses': [f'{i:02d}' for i in range(1, 9)]}
    p = np.ones(28) / 28
    o = np.ones(28) * 30
    snap = {'timing': 't_minus_30m', 'observed_at': {'win': '2026-11-07T00:00:00+00:00'}}
    now = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
    return r, p, o, snap, now


def test_virtual_ticket_never_becomes_actual_purchase():
    """条件通過でも実予算0・実tickets空、仮想だけ100円を保存する。"""
    r, p, o, snap, now = inputs()
    out = shadow.payload(r, p, o, snap, 'S0', 'sha', 'P01', (now + timedelta(minutes=30)).isoformat(), now)
    assert out['budget'] == 0 and out['prediction_tickets'] == []
    assert out['prediction_json']['research_plan']['total_stake_yen'] == 100
    assert out['prediction_json']['finish_order_prediction_available'] is False


def test_no_candidate_is_saved_as_no_virtual_bet():
    """Aの価格範囲外なら予想を残して仮想購入も0円とする。"""
    r, p, o, snap, now = inputs()
    out = shadow.payload(r, p, o, snap, 'M10', 'sha', 'A', (now + timedelta(minutes=10)).isoformat(), now)
    assert out['prediction_json']['research_plan']['tickets'] == []
    assert out['prediction_json']['research_plan']['virtual_budget_yen'] == 0


@pytest.mark.parametrize('seconds', [-1, 0, 29])
def test_post_time_and_short_margin_are_refused(seconds):
    """発走後や余裕不足で作った予想を事前保存扱いにしない。"""
    r, p, o, snap, now = inputs()
    with pytest.raises(ValueError):
        shadow.payload(r, p, o, snap, 'S0', 'sha', 'P01', (now + timedelta(seconds=seconds)).isoformat(), now)


def test_saved_virtual_plan_matches_existing_evaluator_contract():
    """保存する仮想planが既存の公式払戻評価器でそのまま精算できる。"""
    from jra_srb.analysis_store import _evaluate_research_plan, _normalize_selection_items
    r, p, o, snap, now = inputs()
    out = shadow.payload(r, p, o, snap, 'S0', 'sha', 'P01', (now + timedelta(minutes=30)).isoformat(), now)
    forecast = out['prediction_json']
    selection = forecast['research_plan']['tickets'][0]['selection']
    key = '-'.join(_normalize_selection_items('quinella', selection))
    result = _evaluate_research_plan(forecast, {('quinella', key): 1230})
    assert result['virtual_stake_yen'] == 100 and result['virtual_payout_yen'] == 1230
    assert result['virtual_return_rate'] == 12.3 and out['budget'] == 0
