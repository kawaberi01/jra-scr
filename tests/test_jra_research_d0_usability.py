"""概要: 100円精算・日単位区間・不明な採用証拠の拒否を確認する。
作成日: 2026-10-25
入力: 小規模な人工精算行。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_d0_usability.py
注意事項: SQL/HTTP/購入なし。
"""

from jra_srb import jra_research_d0_usability as model


def test_yen_units_and_concentration():
    """100円払戻を倍率にせず、最大的中除去時には該当賭金も除く。"""
    rows = [{'race_id': str(i), 'race_date': '2020-01-01', 'hit': int(i == 0),
        'payout_yen': 1000 if i == 0 else 0} for i in range(4)]
    s = model.summary(rows)
    assert (s['stake_yen'], s['payout_yen'], s['net_yen'], s['roi']) == (400, 1000, 600, 2.5)
    assert s['net_without_largest_hit_yen'] == -300 and s['max_drawdown_yen'] == 300
    assert model.roi_ci(rows)['roi_ci95'] == [2.5, 2.5]


def test_unknown_never_adopts():
    """過去の黒字だけや欠測の証拠では実用購入へ昇格しない。"""
    assert not model.purchase_decision({'roi_ci_lower_above_one': True})['purchase_adopted']
    checks = model.purchase_decision({})['checks']
    assert model.purchase_decision({k: True for k in checks})['purchase_adopted']
