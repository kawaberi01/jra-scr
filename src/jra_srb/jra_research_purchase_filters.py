"""概要: 保存された馬連1位の購入可否を固定10条件で判定・集計する。
作成日: 2026-11-07
入力: 事前確率とT30実オッズ、分離された公式精算行。
出力: 購入マスク、精算・期間集計、開催日bootstrapと固定判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_purchase_filters.py
注意事項: 学習・外部通信・実購入なし。推定Eと確定払戻は異なる。
"""

import numpy as np


def policies():
    """結果を参照せず、E下限5段階×オッズ上限有無の10条件を返す。"""
    return [{'id': f'P{i + 1:02d}', 'min_ev': threshold, 'max_odds': cap}
            for i, (cap, threshold) in enumerate(
                (cap, threshold) for cap in (None, 20.0) for threshold in (1., 1.05, 1.10, 1.15, 1.20))]


def accepts(probability, odds, policy):
    """正解・払戻を使わず、選択済み1組を購入するか判定する。"""
    return bool(probability * odds >= policy['min_ev']
                and (policy['max_odds'] is None or odds <= policy['max_odds']))


def summarize(rows, mask):
    """見送りを支出0として、時系列の購入と公式払戻を集計する。"""
    chosen = [r for r, buy in zip(rows, mask, strict=True) if buy]
    paid = sum(r['paid_yen'] for r in chosen)
    stake = 100 * len(chosen)
    hits = sum(r['hit'] for r in chosen)
    balance, peak, drawdown = 0, 0, 0
    for r in chosen:
        balance += r['paid_yen'] - 100
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    largest = max((r['paid_yen'] for r in chosen), default=0)
    return {'opportunities': len(rows), 'purchases': len(chosen),
            'purchase_rate': len(chosen) / len(rows) if rows else None,
            'purchase_days': len({r['race_date'] for r in chosen}), 'hits': hits,
            'hit_rate': hits / len(chosen) if chosen else None,
            'stake_yen': stake, 'paid_yen': paid, 'net_yen': paid - stake,
            'roi_percent': paid / len(chosen) if chosen else None,
            'mean_ev': float(np.mean([r['ev'] for r in chosen])) if chosen else None,
            'max_drawdown_yen': drawdown, 'largest_hit_yen': largest,
            'net_without_largest_hit_yen': paid - largest - (stake - 100) if hits else -stake,
            'mean_hit_final_to_T30': float(np.mean([
                r['official_payout_yen'] / 100 / r['odds'] for r in chosen if r['hit']])) if hits else None}


def day_arrays(rows, masks, days):
    """全機会日の支出/払戻を列=条件で作り、見送りだけの日も残す。"""
    indices = {day: i for i, day in enumerate(days)}
    stake = np.zeros((len(days), len(masks)), dtype=np.int64)
    paid = np.zeros_like(stake)
    for col, mask in enumerate(masks):
        for r, buy in zip(rows, mask, strict=True):
            if buy:
                i = indices[r['race_date']]
                stake[i, col] += 100
                paid[i, col] += r['paid_yen']
    return stake, paid


def bootstrap(stake, paid, indices):
    """共通の開催日抽出で回収率を計算し、20セル補正下限を返す。

    Args:
        stake: 全機会日×条件の支出円。
        paid: 同じ形状の払戻円。
        indices: seed440の復元抽出日インデックス。行ごとに独立再標本。
    Returns:
        list: 各列の両側95%区間、片側家族95%下限、無購入再標本率。
    Notes:
        0支出の再標本は未定義とし、区間から除外して割合を明示する。
    """
    values = np.full((len(indices), stake.shape[1]), np.nan)
    for start in range(0, len(indices), 200):
        sample = indices[start:start + 200]
        s, p = stake[sample].sum(axis=1), paid[sample].sum(axis=1)
        values[start:start + len(sample)] = np.divide(
            p * 100., s, out=np.full(p.shape, np.nan), where=s > 0)
    result = []
    for col in range(values.shape[1]):
        v = values[:, col]
        finite = v[np.isfinite(v)]
        result.append({'roi_ci95_percent': np.quantile(finite, [.025, .975]).tolist() if len(finite) else None,
                       'roi_family_lower_percent': float(np.quantile(finite, .05 / 20)) if len(finite) else None,
                       'zero_stake_fraction': float(np.mean(~np.isfinite(v)))})
    return result


def decide(total, annual, interval):
    """件数・年別安定・多重比較・単発配当依存から事前固定の採否を返す。"""
    adequate = (total['purchases'] >= 300 and total['hits'] >= 30
                and total['purchase_days'] >= 50 and all(v['purchases'] >= 100 for v in annual.values()))
    checks = {'adequate': adequate,
              'pooled_positive': total['roi_percent'] is not None and total['roi_percent'] > 100,
              'every_year_positive': all(v['roi_percent'] is not None and v['roi_percent'] > 100 for v in annual.values()),
              'family_lower_positive': interval['roi_family_lower_percent'] is not None and interval['roi_family_lower_percent'] > 100,
              'without_largest_positive': total['net_without_largest_hit_yen'] > 0}
    if not total['purchases']:
        label = 'no_opportunities'
    elif not adequate:
        label = 'insufficient'
    elif all(checks.values()):
        label = 'promising_historical_candidate'
    elif checks['pooled_positive']:
        label = 'positive_but_unconfirmed' if checks['every_year_positive'] else 'positive_but_unstable'
    else:
        label = 'unsupported'
    return {'label': label, 'checks': checks, 'purchase_allowed': False, 'unknown_test': False}
