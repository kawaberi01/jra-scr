"""概要: 全馬連の固定候補範囲から期待値最大1組を選び、期間別に評価する。
作成日: 2026-11-07
入力: 保存確率、実オッズ、選択後に分離結合する公式払戻。
出力: 固定3条件の選択、日単位区間、過去/追加期間の採否。
実行例: uv run --frozen --extra ml python scripts/run_jra_purchase_followup.py
注意事項: 学習・外部通信・購入なし。既使用過去と保存入力再計算を区別する。
"""

import numpy as np
from . import jra_research_purchase_filters as prior


def policies():
    """結果を使わず候補範囲とE下限の3条件を返す。"""
    return [{'id': 'A', 'min_p': .03, 'min_odds': 4., 'max_odds': 20., 'min_ev': 1.05},
            {'id': 'B', 'min_p': .03, 'min_odds': 4., 'max_odds': 20., 'min_ev': 1.10},
            {'id': 'C', 'min_p': .05, 'min_odds': 4., 'max_odds': 15., 'min_ev': 1.05}]


def select(probabilities, odds, policy):
    """事前情報だけで適格な最大Eのペアを選び、適格なしではNoneを返す。"""
    p, o = np.asarray(probabilities), np.asarray(odds)
    if p.shape != o.shape or not np.isfinite(p).all() or not np.isfinite(o).all() or np.any(o <= 0):
        raise ValueError('invalid_selection_inputs')
    ev = p * o
    ok = (p >= policy['min_p']) & (o >= policy['min_odds']) & (o <= policy['max_odds']) & (ev >= policy['min_ev'])
    candidates = np.flatnonzero(ok)
    return int(candidates[np.argmax(ev[candidates])]) if len(candidates) else None


def intervals(cells):
    """全機会日を共通抽出し、通常95%区間と今回セル数補正下限を計算する。"""
    days = sorted({r['race_date'] for rows in cells.values() for r in rows})
    if not days:
        return {k: {'roi_ci95_percent': None, 'roi_family_lower_percent': None, 'zero_stake_fraction': 1.}
                for k in cells}
    sample = np.random.default_rng(445).integers(0, len(days), size=(20000, len(days)), dtype=np.int32)
    result = {}
    for name, rows in cells.items():
        stake, paid = prior.day_arrays(rows, [[r['buy'] for r in rows]], days)
        values = []
        for start in range(0, 20000, 200):
            ix = sample[start:start + 200]
            s, p = stake[ix].sum(axis=1)[:, 0], paid[ix].sum(axis=1)[:, 0]
            values.extend((p[s > 0] / s[s > 0] * 100).tolist())
        result[name] = {'roi_ci95_percent': np.quantile(values, [.025, .975]).tolist() if values else None,
                        'roi_family_lower_percent': float(np.quantile(values, .05 / len(cells))) if values else None,
                        'zero_stake_fraction': 1 - len(values) / 20000}
    return result


def assess(cells, forward=False):
    """全条件を選び直さず、購入件数と年別/区間を用いて固定判定する。"""
    ci = intervals(cells)
    result = {}
    for name, rows in cells.items():
        total = prior.summarize(rows, [r['buy'] for r in rows])
        annual = {year: prior.summarize([r for r in rows if r['race_date'].startswith(year)],
                    [r['buy'] for r in rows if r['race_date'].startswith(year)])
                  for year in sorted({r['race_date'][:4] for r in rows})}
        if forward:
            adequate = total['purchases'] >= 100 and total['hits'] >= 20 and total['purchase_days'] >= 30
            checks = {'adequate': adequate, 'pooled_positive': (total['roi_percent'] or 0) > 100,
                      'family_lower_positive': (ci[name]['roi_family_lower_percent'] or 0) > 100,
                      'without_largest_positive': total['net_without_largest_hit_yen'] > 0}
            label = ('no_opportunities' if not total['purchases'] else 'insufficient' if not adequate else
                     'promising_historical_candidate' if all(checks.values()) else 'unsupported')
            decision = {'label': label, 'checks': checks, 'purchase_allowed': False, 'unknown_test': False}
        else:
            decision = prior.decide(total, annual, ci[name])
        result[name] = {'total': total, 'annual': annual, 'interval': ci[name], 'decision': decision}
    return result
