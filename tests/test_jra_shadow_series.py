"""概要: 継続処理の期限と芝限定候補の遡及禁止・実購入分離を検証する。
作成日: 2026-11-07
入力: 合成時刻・事前保存台帳・仮想精算。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_shadow_series.py
注意事項: SQL/HTTP/実購入/プロセス起動なし。
"""

from datetime import date, datetime
import pytest
from jra_srb import jra_research_shadow_series as series


@pytest.mark.parametrize('time,expected', [('2026-11-07T21:00:00+09:00', 'waiting'),
    ('2026-11-08T08:59:00+09:00', 'waiting'), ('2026-11-08T09:00:00+09:00', 'active'),
    ('2026-11-08T18:00:00+09:00', 'waiting'), ('2026-11-21T18:00:00+09:00', 'finished')])
def test_run_window(time, expected):
    """当日稼働窓と最終停止境界が固定される。"""
    assert series.phase(datetime.fromisoformat(time), date(2026, 11, 8), date(2026, 11, 21)) == expected


def inputs(surface='turf'):
    """開始日以後の適格な仮想購入済み台帳を返す。"""
    item = {'case': 'S0', 'status': 'evaluated', 'prediction_id': 'test', 'race_id': '202611080505',
            'server_received_at': '2026-11-08T02:31:00+00:00', 'post_at': '2026-11-08T12:00:00+09:00',
            'virtual_stake_yen': 100, 'research_simulation': {'status': 'available',
            'virtual_stake_yen': 100, 'virtual_payout_yen': 800, 'hit': True}}
    payload = {'prediction_id': 'test', 'created_at': '2026-11-08T02:30:00+00:00', 'budget': 0,
               'prediction_tickets': [], 'pre_race_snapshot': {'race_date': '2026-11-08', 'card': {'surface': surface}}}
    return item, payload


def test_overlay_retains_turf_and_excludes_dirt():
    """同じS0予想を改変せず、ダートだけ派生評価の支出と払戻を0にする。"""
    item, payload = inputs()
    out = series.turf_overlay(item, payload, '2026-11-07T12:00:00+00:00', date(2026, 11, 8))
    assert out['stake_yen'] == 100 and out['paid_yen'] == 800
    item, payload = inputs('dirt')
    out = series.turf_overlay(item, payload, '2026-11-07T12:00:00+00:00', date(2026, 11, 8))
    assert out['stake_yen'] == out['paid_yen'] == out['hits'] == 0
    assert item['virtual_stake_yen'] == 100


def test_overlay_refuses_today_retrofit_and_late_freeze():
    """候補選定前の既知結果を前向き実績に加算できない。"""
    item, payload = inputs()
    with pytest.raises(ValueError):
        series.turf_overlay(item, payload, '2026-11-09T00:00:00+00:00', date(2026, 11, 8))
    with pytest.raises(ValueError):
        series.turf_overlay(item, payload, '2026-11-07T00:00:00+00:00', date(2026, 11, 9))


def test_overlay_refuses_actual_purchase():
    """実予算のあるpayloadを仮想専用の候補へ混ぜない。"""
    item, payload = inputs(); payload['budget'] = 100
    with pytest.raises(ValueError):
        series.turf_overlay(item, payload, '2026-11-07T00:00:00+00:00', date(2026, 11, 8))


def test_more_than_14_days_is_refused():
    """期限が意図せず恒久化しないよう14日を超える窓を拒否する。"""
    with pytest.raises(ValueError):
        series.phase(datetime.fromisoformat('2026-11-07T21:00:00+09:00'), date(2026, 11, 8), date(2026, 11, 22))
