"""概要: 複数点の候補選択と実点数による精算・見送りを検証する。
作成日: 2026-11-07
入力: 合成確率・価格・公式払戻。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_purchase_portfolio.py
注意事項: 学習・外部通信・永続変更なし。
"""

import pytest
from jra_srb import jra_research_purchase_portfolio as policy


def test_multiple_tickets_order_ties_and_cap():
    """E同点はペア順、最大3点、候補不足なら存在する分だけにする。"""
    c = policy.select([.1, .1, .08, .07], [11., 11., 15., 18.])
    assert c['A'] == [3] and c['A2'] == [3, 2] and c['A3'] == [3, 2, 0]


def test_one_winner_is_not_paid_per_ticket():
    """3点購入でも的中払戻は1組分、支出は3組分とする。"""
    race = {'race_id': 'x', 'race_date': '2024-01-01'}
    row = policy.settle(race, [0, 1, 2], 1200, 1)
    s = policy.summary([row])
    assert (s['tickets'], s['stake_yen'], s['paid_yen'], s['roi_percent']) == (3, 300, 1200, 400)
    assert s['purchased_races'] == 1 and s['ticket_hit_rate'] == 1 / 3


def test_remove_largest_hit_removes_only_winning_ticket():
    """最大的中を除いても同レースの外れ点の支出は残す。"""
    r = policy.settle({'race_id': 'x', 'race_date': '2024-01-01'}, [0, 1, 2], 1200, 1)
    assert policy.summary([r])['net_without_largest_hit_yen'] == -200


def test_duplicate_tickets_rejected():
    """重複点で見かけの払戻を水増ししない。"""
    with pytest.raises(ValueError):
        policy.settle({'race_id': 'x', 'race_date': '2024-01-01'}, [1, 1], 1000, 1)


def test_no_bets_no_results_are_undefined():
    """無購入の回収率は未定義で、候補通過にはしない。"""
    assert policy.assess({'A': []}, False)['A']['decision']['label'] == 'no_opportunities'
    assert policy.summary([])['roi_percent'] is None


def test_winner_outside_bad_roster_still_settles_fixed_tickets():
    """名簿矛盾のレースも既存買い目の不的中を除外しない。"""
    r = policy.settle({'race_id': 'x', 'race_date': '2024-01-01'}, [0, 1], 1000, -1)
    assert r['stake_yen'] == 200 and r['paid_yen'] == 0 and r['hits'] == 0
