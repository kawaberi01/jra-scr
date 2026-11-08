"""概要: 固定期待値候補を最大3組へ分散し、実点数の仮想精算を評価する。
作成日: 2026-11-07
入力: 事前確率/実価格と、選択保存後に対応した公式結果。
出力: 各規則の固定組、レース/点数別集計、日単位区間と判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_purchase_operability.py
注意事項: 実購入・学習・外部通信なし。1点100円、最大3点の仮想比較。
"""

import numpy as np


def select(p, o):
    """結果を読まずP01/A/A2/A3を選び、同Eでは元ペア順を保つ。"""
    p, o = np.asarray(p), np.asarray(o)
    if p.shape != o.shape or not np.isfinite(p).all() or not np.isfinite(o).all() or min(o) < 1:
        raise ValueError('invalid_portfolio_market')
    top = int(np.argmax(p))
    choices = [int(i) for i in np.flatnonzero((p >= .03) & (o >= 4) & (o <= 20) & (p * o >= 1.05))]
    ordered = sorted(choices, key=lambda i: (-float(p[i] * o[i]), i))
    return {'P01': [top] if p[top] * o[top] >= 1 else [],
            'A': ordered[:1], 'A2': ordered[:2], 'A3': ordered[:3]}


def settle(race, selected, payout, winner):
    """固定選択を公式正解へ対応させ、複数点の重複を拒否して精算する。"""
    if len(set(selected)) != len(selected) or len(selected) > 3:
        raise ValueError('duplicate_or_excess_tickets')
    hits = int(winner in selected)
    return {'race_id': race['race_id'], 'race_date': race['race_date'], 'indices': selected,
            'tickets': len(selected), 'hits': hits, 'stake_yen': len(selected) * 100,
            'paid_yen': payout * hits, 'official_payout_yen': payout}


def summary(rows):
    """競走数とチケット数を分け、実点数の支出/払戻/依存を集計する。"""
    n, tickets = len(rows), sum(r['tickets'] for r in rows)
    bought = [r for r in rows if r['tickets']]
    hits, paid = sum(r['hits'] for r in rows), sum(r['paid_yen'] for r in rows)
    stake = sum(r['stake_yen'] for r in rows)
    equity = np.r_[0, np.cumsum([r['paid_yen'] - r['stake_yen'] for r in rows], dtype=np.int64)]
    largest = max((r['paid_yen'] for r in rows), default=0)
    return {'opportunities': n, 'purchased_races': len(bought), 'tickets': tickets,
            'purchase_rate': len(bought) / n if n else None,
            'purchase_days': len({r['race_date'] for r in bought}), 'hits': hits,
            'ticket_hit_rate': hits / tickets if tickets else None,
            'race_hit_rate': hits / len(bought) if bought else None,
            'stake_yen': stake, 'paid_yen': paid, 'net_yen': paid - stake,
            'roi_percent': paid / stake * 100 if stake else None,
            'max_drawdown_yen': int(np.max(np.maximum.accumulate(equity) - equity)),
            'net_without_largest_hit_yen': paid - largest - (stake - 100) if hits else -stake}


def assess(cells, historical):
    """全セルを同じ日に再抽出し、事前固定の件数/黒字/区間条件で判定する。"""
    days = sorted({r['race_date'] for rows in cells.values() for r in rows})
    sample = np.random.default_rng(450).integers(0, len(days), (20000, len(days)), dtype=np.int32) if days else None
    result = {}
    for name, rows in cells.items():
        total = summary(rows)
        annual = {y: summary([r for r in rows if r['race_date'].startswith(y)]) for y in sorted({r['race_date'][:4] for r in rows})}
        daily = {d: [0, 0] for d in days}
        for r in rows:
            daily[r['race_date']][0] += r['stake_yen']
            daily[r['race_date']][1] += r['paid_yen']
        array, ratios = np.asarray([daily[d] for d in days]), []
        if days:
            for start in range(0, 20000, 200):
                totals = array[sample[start:start + 200]].sum(axis=1)
                s, p = totals[:, 0], totals[:, 1]
                ratios.extend((p[s > 0] / s[s > 0] * 100).tolist())
        interval = {'roi_ci95_percent': np.quantile(ratios, [.025, .975]).tolist() if ratios else None,
                    'roi_family_lower_percent': float(np.quantile(ratios, .05 / len(cells))) if ratios else None,
                    'zero_stake_fraction': 1 - len(ratios) / 20000}
        adequate = (total['tickets'] >= (300 if historical else 100)
                    and total['hits'] >= (30 if historical else 20)
                    and total['purchase_days'] >= (50 if historical else 30)
                    and (not historical or all(v['tickets'] >= 100 for v in annual.values())))
        checks = {'adequate': adequate, 'pooled_positive': (total['roi_percent'] or 0) > 100,
                  'every_year_positive': all((v['roi_percent'] or 0) > 100 for v in annual.values()),
                  'family_lower_positive': (interval['roi_family_lower_percent'] or 0) > 100,
                  'without_largest_positive': total['net_without_largest_hit_yen'] > 0}
        label = ('no_opportunities' if not total['tickets'] else 'insufficient' if not adequate else
                 'promising_historical_candidate' if all(checks.values()) else 'positive_but_unconfirmed'
                 if checks['pooled_positive'] else 'unsupported')
        result[name] = {'total': total, 'annual': annual, 'interval': interval,
                        'decision': {'label': label, 'checks': checks, 'purchase_allowed': False, 'unknown_test': False}}
    return result
