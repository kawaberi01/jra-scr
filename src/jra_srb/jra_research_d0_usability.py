"""概要: 馬連1点の固定仮想精算・日単位区間・D0の利用範囲判定を行う。
作成日: 2026-10-25
入力: 結果と照合済みの評価行、入力監査の事実。
出力: 回収率とその区間、参考利用/実用購入の採否。
実行例: uv run --frozen --extra ml python scripts/audit_jra_d0_usability.py --help
注意事項: 既使用過去の説明用精算。実購入や購入条件の探索をしない。
"""

from collections import defaultdict

import numpy as np

from .jra_research_r1_live import require


def summary(rows):
    """固定100円馬連1点の全件精算と最大払戻依存を整数円で集計する。"""
    require(bool(rows) and all(type(r['payout_yen']) is int and r['payout_yen'] >= 0 and r['hit'] in (0, 1)
        and (r['hit'] == 1 or r['payout_yen'] == 0) for r in rows), 'usability_ticket_contract')
    stakes, paid = 100*len(rows), sum(r['payout_yen'] for r in rows)
    returns = sorted((r['payout_yen'] for r in rows if r['hit']), reverse=True)
    cumulative = np.cumsum([r['payout_yen']-100 for r in sorted(rows, key=lambda r: r['race_id'])])
    peaks = np.maximum.accumulate(np.r_[0, cumulative])
    return {'races': len(rows), 'hits': sum(r['hit'] for r in rows), 'stake_yen': stakes, 'payout_yen': paid,
        'net_yen': paid-stakes, 'roi': paid/stakes, 'hit_rate': sum(r['hit'] for r in rows)/len(rows),
        'max_drawdown_yen': int(max(peaks-np.r_[0, cumulative])),
        'largest_hit_payout_yen': returns[0] if returns else 0,
        'net_without_largest_hit_yen': paid-sum(returns[:1])-100*(len(rows)-min(1, len(returns))),
        'net_without_top5_hits_yen': paid-sum(returns[:5])-100*(len(rows)-min(5, len(returns)))}


def roi_ci(rows):
    """開催日の全競走をまとめて復元抽出し、回収率の探索的95%区間を返す。"""
    by_day = defaultdict(lambda: [0, 0])
    for row in rows:
        day = by_day[row['race_date']]
        day[0] += row['payout_yen']
        day[1] += 100
    require(bool(by_day), 'usability_empty_days')
    values = np.asarray([by_day[k] for k in sorted(by_day)], dtype=np.int64)
    indices = np.random.default_rng(410).integers(0, len(values), size=(2000, len(values)))
    totals = values[indices].sum(axis=1)
    return {'days': len(values), 'draws': 2000, 'roi_ci95': np.quantile(totals[:, 0]/totals[:, 1], [.025, .975]).tolist()}


def purchase_decision(evidence):
    """不明を合格とせず、実用購入の必須証拠が全て揃う場合だけ採用する。"""
    required = ('prospective_sample_sufficient', 'predictions_and_rule_fixed_before_results',
        'asof_and_history_verified', 'roi_ci_lower_above_one', 'annual_profit_robust', 'not_single_hit_dependent')
    checks = {k: evidence.get(k) is True for k in required}
    return {'purchase_adopted': all(checks.values()), 'checks': checks,
        'decision': 'adopt' if all(checks.values()) else 'do_not_adopt_currently',
        'failed_or_unproven': [k for k, v in checks.items() if not v]}
