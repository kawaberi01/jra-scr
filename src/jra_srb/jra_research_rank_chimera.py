"""概要: H2の確率精度を保ちつつ市場有力候補間の順位学習を追加する。
作成日: 2026-10-24
入力: spec355と同じ公開特徴/市場、訓練時だけ正解ペア。
出力: 保存可能な順位学習/凸混合モデルと全馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_rank_chimera.py --help
注意事項: SQL/HTTP/実購入なし。結果を推論へ渡さず、将来の的中を保証しない。
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from threadpoolctl import threadpool_limits

from . import jra_research_market_chimera as core
from .jra_research_r1_live import require
from .jra_research_resources import check_memory


PROTOCOL = 'spec360-rank-condition-chimera-v1'
RANK_WEIGHTS = {'R25': .25, 'R50': .5, 'R100': 1.}
ORDER = ('H2', 'G50', 'R25', 'R50', 'R100')


def prepare_rank_data(records, weight):
    """市場上位5組の訓練負例と、競走等重みの対比較重みを作る。

    Args:
        records: 対象年より前の正解付き教師。
        weight: CEに追加する対比較損失の非負係数。
    Returns:
        既存H2訓練行列と正解/市場負例の整数位置、重み。
    Notes:
        負例選択に正解を使うのは正解組の除外だけ。現在予測には使用しない。
    """
    require(np.isfinite(weight) and weight >= 0, 'rank_invalid_weight')
    data = core.pack(records, 'H2')
    negatives, positives, weights = [], [], []
    for r, start, target in zip(records, data['starts'], data['targets'], strict=True):
        negative = [int(i) for i in np.argsort(-r['market'], kind='stable')[:5]
                    if int(start)+int(i) != int(target)]
        require(4 <= len(negative) <= 5, 'rank_negative_count')
        negatives.extend(int(start)+i for i in negative)
        positives.extend([int(target)]*len(negative))
        weights.extend([weight/(len(records)*len(negative))]*len(negative))
    data.update(negative=np.asarray(negatives, dtype=np.int32), positive=np.asarray(positives, dtype=np.int32),
                rank_weights=np.asarray(weights, dtype=float))
    return data


def logits(flat, data):
    """市場offsetとH2の共通/条件係数から全訓練ペアのlogitを作る。"""
    x = data['x']
    beta = flat.reshape(len(data['names']), x.shape[1])
    z = data['offset'].copy()
    for start in range(0, len(x), 50000):
        z[start:start+50000] += x[start:start+50000].astype(float) @ beta[0]
    for c, indices in data['indices'].items():
        for start in range(0, len(indices), 50000):
            ix = indices[start:start+50000]
            z[ix] += x[ix].astype(float) @ beta[c]
    return z, beta


def objective(flat, data):
    """CEと有力負例対比較の合成損失・解析勾配を返す。

    Args:
        flat: 共通/条件差分係数を連結した配列。
        data: 過去教師の行列と対比較位置。
    Returns:
        正則化済み損失と同形状の勾配。
    """
    x = data['x']
    z, beta = logits(flat, data)
    p, normalizer = core.probabilities(z, data['starts'], data['groups'])
    loss = np.mean(normalizer-z[data['targets']])
    p[data['targets']] -= 1
    p /= data['nr']
    difference = z[data['negative']]-z[data['positive']]
    loss += np.sum(data['rank_weights']*np.logaddexp(0, difference))
    derivative = data['rank_weights']*expit(difference)
    np.add.at(p, data['negative'], derivative)
    np.add.at(p, data['positive'], -derivative)
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
    """過去教師から順位追加H2を学習し、既存推論器と互換の係数を包む。

    Args:
        records: 年境界を限定した教師。
        case: R25/R50/R100の固定強度。
    Returns:
        基底H2モデルと追加損失の来歴を持つ保存可能な辞書。
    Raises:
        ResearchError: 未対応構成、非収束、メモリ制約違反。
    """
    require(case in RANK_WEIGHTS, 'rank_unknown_case')
    data = prepare_rank_data(records, RANK_WEIGHTS[case])
    with threadpool_limits(limits=1):
        result = minimize(objective, np.zeros(len(data['names'])*data['x'].shape[1]), args=(data,),
                          jac=True, method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'rank_optimizer_failed')
    check_memory(core.base.MEMORY_LIMIT)
    fitted = {'protocol': core.PROTOCOL, 'case': 'H2', 'scale': data['scale'],
        'coef': result.x.reshape(len(data['names']), -1), 'contexts': data['names'],
        'context_counts': data['context_counts'], 'horse_features': list(core.base.FEATURES),
        'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
        'train_races': len(records), 'optimizer': {'success': True, 'iterations': int(result.nit),
            'objective': float(result.fun), 'rank_weight': RANK_WEIGHTS[case]}}
    return {'protocol': PROTOCOL, 'case': case, 'kind': 'rank', 'base_model': fitted, 'market_mix_weight': 1.}


def wrap(fitted, case):
    """既存H2を再学習せず、基準または市場50%混合として包む。"""
    require(case in ('H2', 'G50'), 'rank_unknown_wrapper')
    return {'protocol': PROTOCOL, 'case': case, 'kind': 'mix', 'base_model': fitted,
            'market_mix_weight': .5 if case == 'G50' else 1.}


def predict(fitted, record):
    """固定係数から順位追加/凸混合の確率を返し、現在結果を無視する。"""
    require(fitted['protocol'] == PROTOCOL, 'rank_model_contract')
    p = core.predict(fitted['base_model'], core.clean(record))
    weight = fitted['market_mix_weight']
    require(0 <= weight <= 1, 'rank_invalid_mix')
    p = weight*p+(1-weight)*np.asarray(record['market'])
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'rank_invalid_probability')
    return p
