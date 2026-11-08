"""概要: S0の現在入力で確率CEを使わず対比較順位だけを学習するS2。
作成日: 2026-11-05
入力: S0の市場・当日属性・競走条件、訓練時だけ正解ペア。
出力: 14列の順位モデルと全馬連スコア、順位評価集計。
実行例: uv run --frozen --extra ml python scripts/run_jra_rank_current.py
注意事項: スコアは確率ではない。追加取得・SQL・購入・既定変更なし。
"""

from collections import defaultdict

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from threadpoolctl import threadpool_limits

from . import jra_research_current_attributes as base
from . import jra_research_rank_chimera as rank
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

PROTOCOL = 'spec435-current-pairwise-rank-S2-v1'
NEGATIVE_TOP = 5


def pack(records):
    """S0の尺度・条件を再利用し、競走等重みの有力負例対比較を作る。"""
    original = base.pack(records)
    differences, offsets, weights, positives, negatives = [], [], [], [], []
    memberships = defaultdict(list)
    ids = {name: i for i, name in enumerate(original['names'])}
    for r, start, target in zip(records, original['starts'], original['targets'], strict=True):
        negative = [int(i) for i in np.argsort(-r['market'], kind='stable')[:NEGATIVE_TOP] if int(i) != int(r['winner'])]
        require(4 <= len(negative) <= 5, 'S2_negative_count')
        begin = len(differences)
        for i in negative:
            ix = int(start)+i
            differences.append(original['x'][ix].astype(float)-original['x'][target].astype(float))
            offsets.append(float(original['offset'][ix]-original['offset'][target]))
            weights.append(1/(len(records)*len(negative)))
            positives.append(int(target))
            negatives.append(ix)
        for name in base.core.base.contexts(r, 'C2'):
            if name in ids:
                memberships[ids[name]].extend(range(begin, len(differences)))
    data = {'x': np.asarray(differences, dtype=float), 'offset': np.asarray(offsets),
            'weights': np.asarray(weights), 'indices': {c: np.asarray(ix, dtype=np.int32) for c, ix in memberships.items()},
            'names': original['names'], 'scale': original['scale'], 'context_counts': original['context_counts'],
            'positive': np.asarray(positives), 'negative': np.asarray(negatives), 'nr': len(records)}
    require(abs(data['weights'].sum()-1) < 1e-12, 'S2_race_equal_weights')
    check_memory(base.core.base.MEMORY_LIMIT)
    return data


def objective(flat, data):
    """対比較ロジスティック損失とL2だけの値・解析勾配を返す。"""
    difference, beta = rank.logits(flat, data)
    loss = float(data['weights'] @ np.logaddexp(0, difference))
    derivative = data['weights']*expit(difference)
    penalty = np.ones((len(beta), 1))
    penalty[0] = .1
    gradient = penalty*beta
    gradient[0] += data['x'].T @ derivative
    for context, ix in data['indices'].items():
        gradient[context] += data['x'][ix].T @ derivative[ix]
    return loss+float(np.sum(penalty*beta*beta)/2), gradient.ravel()


def fit(records):
    """過去教師だけで順位専用のS2係数を一回学習する。"""
    data = pack(records)
    with threadpool_limits(limits=1):
        result = minimize(objective, np.zeros(len(data['names'])*14), args=(data,), jac=True,
                          method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'S2_optimizer')
    check_memory(base.core.base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': 'S2', 'input_fields': list(base.FIELDS),
            'output_kind': 'rank_score_not_probability', 'objective_kind': 'pairwise_logistic_only',
            'negative_top': NEGATIVE_TOP, 'scale': data['scale'], 'coef': result.x.reshape(len(data['names']), 14),
            'contexts': data['names'], 'context_counts': data['context_counts'],
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'train_races': len(records), 'train_comparisons': len(data['x']),
            'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def scores(fitted, record):
    """現在情報だけから全ペアの有限スコアを返し、確率変換はしない。"""
    require(fitted['protocol'] == PROTOCOL and fitted['input_fields'] == list(base.FIELDS)
            and fitted['output_kind'] == 'rank_score_not_probability', 'S2_model_contract')
    r = base.clean(record)
    require(fitted['trained_through'] < r['race_date'], 'S2_future_training')
    beta = fitted['coef'][0].copy()
    for name in base.core.base.contexts(r, 'C2'):
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    values = np.log(r['market'])+(base.matrix(r)/fitted['scale'].astype(np.float32)) @ beta
    require(np.isfinite(values).all() and values.shape == np.asarray(r['market']).shape, 'S2_score_contract')
    return values


def summary(rows):
    """順位と固定100円一票の精算を整数金額から集計する。"""
    require(bool(rows), 'S2_empty_rows')
    n, hits, paid = len(rows), sum(r['hit'] for r in rows), sum(r['paid_yen'] for r in rows)
    return {'races': n, 'days': len({r['race_date'] for r in rows}), 'hits': hits, 'hit_rate': hits/n,
            'stake_yen': n*100, 'paid_yen': paid, 'net_yen': paid-n*100, 'roi_percent': paid/n,
            'mean_winner_rank': float(np.mean([r['winner_rank'] for r in rows]))}


def comparison_ci(candidate, reference):
    """同じ開催日を同時復元抽出し、的中率差と回収率ポイント差を返す。"""
    require([r['race_id'] for r in candidate] == [r['race_id'] for r in reference], 'S2_ci_roster')
    values = defaultdict(lambda: np.zeros(3, dtype=np.int64))
    for a, b in zip(candidate, reference, strict=True):
        require(a['race_date'] == b['race_date'], 'S2_ci_dates')
        values[a['race_date']] += [1, a['hit']-b['hit'], a['paid_yen']-b['paid_yen']]
    days = np.asarray([values[k] for k in sorted(values)])
    ix = np.random.default_rng(435).integers(0, len(days), size=(2000, len(days)))
    totals = days[ix].sum(axis=1)
    return {'days': len(days), 'draws': 2000, 'seed': 435,
            'hit_rate_difference_ci95': np.quantile(totals[:, 1]/totals[:, 0], [.025, .975]).tolist(),
            'roi_difference_pp_ci95': np.quantile(totals[:, 2]/totals[:, 0], [.025, .975]).tolist()}


def grouped(rows):
    """競馬場・芝ダート・距離帯・季節の全群を説明用に集計する。"""
    result = {'all': summary(rows)}
    for field in ('course', 'surface', 'distance_band', 'season'):
        keys = sorted({str(r[field]) for r in rows})
        result[field] = {key: summary([r for r in rows if str(r[field]) == key]) for key in keys}
    return result
