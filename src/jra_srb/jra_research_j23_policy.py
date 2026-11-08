"""概要: J23の既存10購入政策を共通化し、過去月だけから補正係数を求める。
作成日: 2026-10-23
入力: 元J23の購入行、前月までの完全な月別購入履歴。
出力: 補正係数と100円単位の仮想賭金。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_j23_live.py
注意事項: SQL・ファイル更新・学習なし。価格補正は的中分限定の仮説。
"""

from datetime import date
import math

from .jra_research_contracts import ResearchError


def band(odds):
    """購入時オッズを結果非依存の固定3区分へ写像する。"""
    return 'under10' if odds < 10 else '10to30' if odds < 30 else '30plus'


def estimate(past):
    """過去購入だけから既存式の縮約確率係数と的中時価格係数を返す。"""
    expected = sum(r['ticket_probability'] for r in past)
    hits = sum(r['payout'] > 0 for r in past)
    ratio = (hits+20)/(expected+20)
    variance = sum(r['ticket_probability']*(1-r['ticket_probability']) for r in past)
    lower = max(0., ratio-1.28*math.sqrt(variance)/(expected+20))
    wins = [r for r in past if r['payout'] > 0]
    actual = sum(r['payout'] for r in wins)
    quoted = sum(r['stake']*r['ticket_odds'] for r in wins)
    price = (actual+100000)/(quoted+100000)
    return dict(probability=min(1.25, max(.5, ratio)),
                conservative=min(1.25, lower), price=min(1.05, max(.65, price)),
                bets=len(past), hits=hits, expected_hits=expected)


def policy_stake(name, row, parameters):
    """既存10案の式で元の選択済みペアの仮想賭金を返す。"""
    p, odds = row['ticket_probability'], row['ticket_odds']
    if name == 'Q08':
        return 100*min(6, int(6000/odds/100))
    if name == 'Q09':
        return 600 if row['pair_count'] <= 105 else 0
    if name == 'Q10':
        return 600 if row['r1_agrees'] else 0
    global_fit = parameters['global']
    factors = {
        'Q01': .9,
        'Q02': global_fit['price'],
        'Q03': parameters['price_bands'][band(odds)]['price'],
        'Q04': global_fit['probability'],
        'Q05': global_fit['probability']*global_fit['price'],
        'Q06': parameters['recent']['probability'],
        'Q07': global_fit['conservative'],
    }
    if name in factors:
        return 600 if min(1., p*factors[name])*odds >= 1.05 else 0
    raise ValueError(name)


def monthly_parameters(months, target_month):
    """欠測月と未来行を拒否し、対象月より前だけから既存補正係数を求める。

    Args:
        months: 完全と確認済みのYYYY-MMから元J23購入行への辞書。購入なし月も空配列で必要。
        target_month: 係数を固定するYYYY-MM。
    Returns:
        全過去・直近3暦月・価格帯別の係数と使用月。
    Raises:
        ResearchError: 月の欠落、形式不正、未来結果、不正購入行。
    """
    try:
        target = date.fromisoformat(target_month+'-01')
        ordered = sorted(months)
        if not ordered or any(str(date.fromisoformat(m+'-01'))[:7] != m for m in ordered):
            raise ValueError('month')
        first = date.fromisoformat(ordered[0]+'-01')
        required = []
        ordinal = first.year*12+first.month-1
        last = target.year*12+target.month-1
        while ordinal < last:
            y, m = divmod(ordinal, 12)
            required.append(f'{y:04d}-{m+1:02d}')
            ordinal += 1
        if ordered != required or len(ordered) < 3:
            raise ResearchError('j23_missing_complete_prior_months', 2)
        past = []
        for month in ordered:
            for row in months[month]:
                if (row['race_date'][:7] != month or row['stake'] != 600
                        or not 0 < row['ticket_probability'] <= 1
                        or not math.isfinite(row['ticket_odds']) or row['ticket_odds'] < 1
                        or row['payout'] < 0 or row['payout'] % 6 != 0):
                    raise ResearchError('j23_invalid_coefficient_history', 2)
                past.append(row)
        recent = [r for month in ordered[-3:] for r in months[month]]
        return {'target_month': target_month, 'trained_through_month': ordered[-1],
                'recent_months': ordered[-3:], 'global': estimate(past), 'recent': estimate(recent),
                'price_bands': {b: estimate([r for r in past if band(r['ticket_odds']) == b])
                                for b in ('under10', '10to30', '30plus')}}
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ResearchError('j23_invalid_coefficient_history', 2) from None
