"""概要: T10と時点を揃えたS10、およびT30からの市場変化を使うM10を学習する。
作成日: 2026-11-07
入力: T10現在市場/当日属性、M10のみT30市場、教師では正解ペア。
出力: 14/16列の固定モデルと全馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_ten_minute.py
注意事項: 市場変化はT10まで。結果/未来価格の特徴利用、外部取得なし。
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits
from . import jra_research_current_attributes as base
from .jra_research_resources import check_memory


def movement(record):
    """時点内の正規化市場変化2列をT10期待値で中心化する。"""
    q, pl = np.asarray(record['market']), np.asarray(record['pl'])
    early_q, early_pl = np.asarray(record['early_market']), np.asarray(record['early_pl'])
    if q.shape != early_q.shape or pl.shape != early_pl.shape or min(early_q) <= 0 or min(early_pl) <= 0:
        raise ValueError('invalid_early_market')
    x = np.column_stack((np.clip(np.log(q / early_q), -5, 5), np.clip(np.log(pl / early_pl), -5, 5)))
    x -= q @ x
    if not np.isfinite(x).all():
        raise ValueError('nonfinite_movement')
    return x.astype(np.float32)


def matrix(record):
    """既存14列を維持し、市場変化だけを2列追加する。"""
    return np.column_stack((base.matrix(record), movement(record))).astype(np.float32)


def fit(records, case):
    """S10は既存S0学習、M10は同じ目的関数へ16列を渡して一度学習する。"""
    if case == 'S10':
        fitted = base.fit(records)
        return fitted | {'case': 'S10', 'market_time': 'T-10m'}
    if case != 'M10':
        raise ValueError('unknown_ten_minute_case')
    data = base.pack(records)
    extra = np.concatenate([movement(r) for r in records])
    scale = base.core.training_scale(extra)
    extra /= scale.astype(np.float32)
    data['x'] = np.column_stack((data['x'], extra)).astype(np.float32)
    data['scale'] = np.r_[data['scale'], scale]
    check_memory(base.core.base.MEMORY_LIMIT)
    with threadpool_limits(limits=1):
        result = minimize(base.core.objective, np.zeros(len(data['names']) * 16), args=(data,), jac=True,
                          method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    if not result.success or not np.isfinite(result.x).all():
        raise ValueError('M10_optimizer_failed')
    return {'protocol': 'spec451-M10', 'case': 'M10', 'market_time': 'T-10m', 'scale': data['scale'],
            'coef': result.x.reshape(len(data['names']), 16), 'contexts': data['names'],
            'context_counts': data['context_counts'], 'train_races': len(records),
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """同年以降のT10入力だけで推論し、教師期間以降であることを要求する。"""
    if fitted['case'] == 'S10':
        return base.predict(fitted, record)
    if fitted['protocol'] != 'spec451-M10' or fitted['trained_through'] >= record['race_date']:
        raise ValueError('M10_protocol_or_training_boundary')
    beta = fitted['coef'][0].copy()
    for context in base.core.base.contexts(record, 'C2'):
        if context in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(context)]
    return softmax(np.log(record['market']) + (matrix(record) / fitted['scale'].astype(np.float32)) @ beta)


def from_observations(early, late):
    """保存T30/T10の名簿と時刻を照合し、現時点だけの入力を構築する。"""
    if early['race_id'] != late['race_id'] or early['timing'] != 't_minus_30m' or late['timing'] != 't_minus_10m':
        raise ValueError('paired_observation_identity')
    from datetime import datetime
    if max(datetime.fromisoformat(t) for t in early['observed_at'].values()) > min(datetime.fromisoformat(t) for t in late['observed_at'].values()):
        raise ValueError('early_observation_after_late')
    r, e = base.from_capture(late), base.from_capture(early)
    if r['horses'] != e['horses']:
        raise ValueError('paired_roster_changed')
    return r | {'early_market': e['market'], 'early_pl': e['pl']}
