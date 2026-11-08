"""概要: 単勝・馬連市場を基準に予想論の部品と条件差で確率を補正する。
作成日: 2026-10-24
入力: 同時点の市場/単勝PL、前日15馬特徴、訓練時だけ正解ペア。
出力: T0/P0/H0/H1/H2の保存モデルと馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_market_chimera.py --help
注意事項: 探索用。現在結果を推論へ使わず、購入判断・既定変更をしない。
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from . import jra_research_condition_chimera as base
from .jra_research_chimera_thirty_model import probabilities, training_scale
from .jra_research_r1_live import require
from .jra_research_resources import check_memory


PROTOCOL = 'spec355-market-condition-chimera-v1'
CASES = ('T0', 'P0', 'H0', 'H1', 'H2')
FIELDS = (*base.PRE_RACE_FIELDS, 'market', 'pl')


def clean(record):
    """公開特徴と同時点市場だけを通し、結果・精算を除外する。"""
    return {key: record[key] for key in FIELDS}


def context_case(case):
    """共通学習か条件/季節差分学習かを既存構成へ対応付ける。"""
    require(case in CASES, 'market_chimera_unknown_case')
    return 'C2' if case in ('H1', 'H2') else 'C0'


def matrix(record, case):
    """市場の温度/乖離と能力部品を対称ペア特徴にし、市場期待値で中心化する。"""
    require(case in CASES, 'market_chimera_unknown_case')
    n = len(record['horses'])
    q, pl = np.asarray(record['market'], dtype=float), np.asarray(record['pl'], dtype=float)
    require(q.shape == pl.shape == (n*(n-1)//2,) and np.isfinite(q).all() and np.isfinite(pl).all()
            and np.all(q > 0) and np.all(pl > 0) and abs(q.sum()-1) < 1e-8
            and abs(pl.sum()-1) < 1e-8, 'market_chimera_market_contract')
    gap = np.clip(np.log(pl/q), -10, 10)
    out = np.log(q)[:, None]
    if case != 'T0':
        out = np.column_stack((out, gap))
    if case.startswith('H'):
        out = np.column_stack((out, base.pair_matrix(record, list(range(15)))))
    if case == 'H2':
        ij = base.pairs(n)
        horse = np.asarray(record['x'])
        clock = np.mean(horse[ij, 0], axis=1)
        reliability = np.mean(horse[ij, 9], axis=1)
        out = np.column_stack((out, gap*clock, gap*reliability))
    out -= q @ out
    require(np.isfinite(out).all(), 'market_chimera_nonfinite_matrix')
    return out.astype(np.float32)


def pack(records, case):
    """既存の競走境界と条件件数を再利用し、市場補正行列を作る。"""
    data = base.pack(records, context_case(case), list(range(15)) if case.startswith('H') else [0])
    first = matrix(clean(records[0]), case)
    x = np.empty((len(data['x']), first.shape[1]), dtype=np.float32)
    for r, start, count in zip(records, data['starts'], data['counts'], strict=True):
        x[start:start+count] = matrix(clean(r), case)
    data['x'] = x
    scale = training_scale(x)
    x /= scale.astype(np.float32)
    data['scale'] = scale
    data['offset'] = np.log(np.concatenate([r['market'] for r in records]))
    return data


def objective(flat, data):
    """市場offsetと条件差分の正則化対数損失および解析勾配を返す。"""
    x = data['x']
    beta = flat.reshape(len(data['names']), x.shape[1])
    logits = data['offset'].copy()
    for start in range(0, len(x), 50000):
        logits[start:start+50000] += x[start:start+50000].astype(float) @ beta[0]
    for c, indices in data['indices'].items():
        for start in range(0, len(indices), 50000):
            ix = indices[start:start+50000]
            logits[ix] += x[ix].astype(float) @ beta[c]
    p, normalizer = probabilities(logits, data['starts'], data['groups'])
    loss = np.mean(normalizer-logits[data['targets']])
    p[data['targets']] -= 1
    p /= data['nr']
    penalty = np.ones((len(beta), 1))
    penalty[0] = .1
    gradient = penalty*beta
    for start in range(0, len(x), 50000):
        gradient[0] += x[start:start+50000].astype(float).T @ p[start:start+50000]
    for c, indices in data['indices'].items():
        for start in range(0, len(indices), 50000):
            ix = indices[start:start+50000]
            gradient[c] += x[ix].astype(float).T @ p[ix]
    return float(loss+np.sum(penalty*beta*beta)/2), gradient.ravel()


def fit(records, case):
    """指定済みの過去教師だけで市場補正を学習し、来歴を保存可能な形で返す。"""
    data = pack(records, case)
    with threadpool_limits(limits=1):
        result = minimize(objective, np.zeros(len(data['names'])*data['x'].shape[1]), args=(data,),
                          jac=True, method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'market_chimera_optimizer_failed')
    check_memory(base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': case, 'scale': data['scale'],
            'coef': result.x.reshape(len(data['names']), -1), 'contexts': data['names'],
            'context_counts': data['context_counts'], 'horse_features': list(base.FEATURES),
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'train_races': len(records), 'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """訓練より後の公開特徴と時点市場から全馬連確率を返す。"""
    require(fitted['protocol'] == PROTOCOL and fitted['horse_features'] == list(base.FEATURES), 'market_chimera_model_contract')
    record = clean(record)
    require(fitted['trained_through'] < record['race_date'], 'market_chimera_future_training')
    x = matrix(record, fitted['case'])/fitted['scale'].astype(np.float32)
    beta = fitted['coef'][0].copy()
    for name in base.contexts(record, context_case(fitted['case'])):
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    p = softmax(np.log(record['market'])+x @ beta)
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'market_chimera_invalid_probability')
    return p
