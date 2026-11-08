"""概要: 購入限定条件の境界・精算・見送り日・固定採否を検証する。
作成日: 2026-11-07
入力: 小規模な合成の事前情報と公式精算。
出力: pytest検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_purchase_filters.py
注意事項: 外部通信・既存成果物変更なし。
"""

import numpy as np

from jra_srb import jra_research_purchase_filters as model


def row(day, hit=0, payout=1000):
    """小規模精算用の行を返す。"""
    return {'race_date': day, 'hit': hit, 'paid_yen': payout * hit,
            'official_payout_yen': payout, 'probability': .1, 'odds': 10., 'ev': 1.}


def test_ten_fixed_policies_and_boundaries():
    """10条件の対応とE/オッズ上限の包含境界を確認する。"""
    pp = model.policies()
    assert len(pp) == 10 and len({p['id'] for p in pp}) == 10
    assert model.accepts(.05, 20, pp[5])
    assert not model.accepts(.05, 20.01, pp[5])
    assert model.accepts(.10, 10.5, pp[1])
    assert not model.accepts(.10, 10.499, pp[1])


def test_result_never_changes_buy_or_pair():
    """購入判定は正解や払戻を受け取らず選択済み1組だけを使う。"""
    r = row('2024-01-01')
    before = model.accepts(r['probability'], r['odds'], model.policies()[0])
    r.update(hit=1, paid_yen=999999, winner=999)
    assert model.accepts(r['probability'], r['odds'], model.policies()[0]) == before


def test_purchase_settlement_and_no_purchases():
    """見送りは支出0、的中払戻は公式値で最大1件除外を再精算する。"""
    rows = [row('2024-01-01'), row('2024-01-02', 1), row('2024-01-03')]
    s = model.summarize(rows, [False, True, True])
    assert (s['stake_yen'], s['paid_yen'], s['roi_percent'], s['net_yen']) == (200, 1000, 500, 800)
    assert s['net_without_largest_hit_yen'] == -100
    empty = model.summarize(rows, [False] * 3)
    assert empty['roi_percent'] is None and empty['stake_yen'] == 0


def test_bootstrap_keeps_skipped_opportunity_day():
    """全日見送りの再標本を未定義として残し補正下限を通常区間と区別する。"""
    rows = [row('2024-01-01', 1), row('2024-01-02')]
    stake, paid = model.day_arrays(rows, [[True, False]], ['2024-01-01', '2024-01-02'])
    assert stake[:, 0].tolist() == [100, 0]
    result = model.bootstrap(stake, paid, np.array([[1, 1], [0, 1], [0, 0]]))[0]
    assert result['zero_stake_fraction'] == 1 / 3
    assert result['roi_ci95_percent'] == [1000., 1000.]


def test_point_profit_insufficient_does_not_pass():
    """高回収1的中でも必要件数・年別・補正下限を緩和しない。"""
    total = model.summarize([row('2024-01-01', 1)], [True])
    annual = {str(y): total for y in (2024, 2025, 2026)}
    interval = {'roi_family_lower_percent': 200.}
    assert model.decide(total, annual, interval)['label'] == 'insufficient'
    adequate = total | {'purchases': 900, 'hits': 50, 'purchase_days': 100, 'net_without_largest_hit_yen': 1000}
    assert model.decide(adequate, {str(y): adequate for y in (2024, 2025, 2026)}, interval)['label'] == 'promising_historical_candidate'
    assert model.decide(adequate, {str(y): adequate for y in (2024, 2025, 2026)}, {'roi_family_lower_percent': 99})['label'] == 'positive_but_unconfirmed'
