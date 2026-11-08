"""概要: 上位負例だけの偏りを除き、全非正解ペアとの順位学習を行うS2B。
作成日: 2026-11-05
入力: S0と同じ市場/当日属性/条件、訓練時の正解ペア。
出力: S2共通推論契約・spec436訓練来歴を持つS2Bモデル。
実行例: uv run --frozen --extra ml python scripts/run_jra_rank_current_all.py
注意事項: スコアは確率ではない。CE・購入・SQL・追加取得なし。
"""

from collections import defaultdict

import numpy as np
from scipy.optimize import minimize
from threadpoolctl import threadpool_limits

from . import jra_research_rank_current as previous
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

base = previous.base
TRAINING_PROTOCOL = 'spec436-current-all-negative-rank-S2B-v1'
summary, grouped, comparison_ci = previous.summary, previous.grouped, previous.comparison_ci


def pack(records):
    """S0の尺度と条件を保持し、正解対全非正解の比較差分を作る。"""
    original = base.pack(records)
    total = sum(int(n)-1 for n in original['counts'])
    x = np.empty((total, 14), dtype=float)
    offset, weights = np.empty(total), np.empty(total)
    memberships = defaultdict(list)
    ids = {name: i for i, name in enumerate(original['names'])}
    cursor = 0
    for r, start, target, count in zip(records, original['starts'], original['targets'], original['counts'], strict=True):
        local = np.arange(int(start), int(start+count))
        negative = local[local != target]
        stop = cursor+len(negative)
        x[cursor:stop] = original['x'][negative].astype(float)-original['x'][target].astype(float)
        offset[cursor:stop] = original['offset'][negative]-original['offset'][target]
        weights[cursor:stop] = 1/(len(records)*len(negative))
        for name in base.core.base.contexts(r, 'C2'):
            if name in ids:
                memberships[ids[name]].append(np.arange(cursor, stop, dtype=np.int32))
        cursor = stop
    require(cursor == total and abs(weights.sum()-1) < 1e-12, 'S2B_comparison_contract')
    data = {'x': x, 'offset': offset, 'weights': weights,
            'indices': {c: np.concatenate(ix) for c, ix in memberships.items()},
            'names': original['names'], 'scale': original['scale'], 'context_counts': original['context_counts'], 'nr': len(records)}
    check_memory(base.core.base.MEMORY_LIMIT)
    return data


def fit(records):
    """全負例の純対比較目的を、固定した年境界で一度学習する。"""
    data = pack(records)
    with threadpool_limits(limits=1):
        result = minimize(previous.objective, np.zeros(len(data['names'])*14), args=(data,), jac=True,
                          method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'S2B_optimizer')
    check_memory(base.core.base.MEMORY_LIMIT)
    return {'protocol': previous.PROTOCOL, 'training_protocol': TRAINING_PROTOCOL, 'case': 'S2B',
            'variant': 'S2B_all_negatives', 'input_fields': list(base.FIELDS), 'output_kind': 'rank_score_not_probability',
            'objective_kind': 'pairwise_logistic_only', 'negative_top': 'all', 'scale': data['scale'],
            'coef': result.x.reshape(len(data['names']), 14), 'contexts': data['names'], 'context_counts': data['context_counts'],
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'train_races': len(records), 'train_comparisons': len(data['x']),
            'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def scores(fitted, record):
    """S2Bの訓練来歴を確認し、S2共通の14列スコア契約で推論する。"""
    require(fitted['training_protocol'] == TRAINING_PROTOCOL and fitted['negative_top'] == 'all', 'S2B_model_contract')
    return previous.scores(fitted, record)
