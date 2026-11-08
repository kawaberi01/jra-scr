"""概要: 30仮説の市場offset学習と、結果を参照しない馬連確率推論を行う。
作成日: 2026-10-22
入力: spec241固定特徴、学習期間の正解組、過去OOS正解確率。
出力: 再読込可能な線形/木/混合モデルと最適化証跡。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_chimera_thirty.py
注意事項: 尺度と重みは学習期間だけから算出。実購入・外部通信なし。
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp, softmax, expit
from sklearn.tree import DecisionTreeRegressor
from threadpoolctl import threadpool_limits

from .jra_research_chimera_thirty_features import SLICES, LIMIT, old, pl_pairs
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

CASES = tuple(f'J{i:02d}' for i in range(1, 31))
PREDICT_FIELDS = ('x', 'addition', 'basic', 'market', 'pl', 'styles', 'density', 'group')


def clean_record(record):
    """推論に許可した前日特徴と市場だけを渡し、結果/払戻を遮断する。"""
    return {key: record[key] for key in PREDICT_FIELDS}


def matrix(record, case):
    """一競走の対称ペア特徴を作り、市場期待値で中心化する。"""
    n = len(record['x'])
    left, right = old.pairs(n).T
    logq = np.log(record['market'])
    if case == 'R1':
        horse = record['basic']
    else:
        horse = record['x']
        number = int(case[1:])
        if 2 <= number <= 22:
            horse = np.column_stack((horse, record['addition'][:, SLICES[number]]))
        elif number == 28:
            horse = np.column_stack((horse, record['addition']))
    a, b = horse[left], horse[right]
    result = np.column_stack((logq, (a+b)/2, np.abs(a-b)))
    if case in ('J23', 'J28'):
        gap = np.clip(np.log(record['pl']/record['market']), -10, 10)
        confidence = (record['x'][left, 9]+record['x'][right, 9])/2
        clock = (record['x'][left, 0]+record['x'][right, 0])/2
        result = np.column_stack((result, gap, gap*clock, gap*confidence))
    if case in ('J24', 'J28'):
        sa, sb = record['styles'][left], record['styles'][right]
        same = (1-np.abs(sa-sb))*record['density']
        front = ((sa <= .3)&(sb <= .3))*record['density']
        clock = (record['x'][left, 0]+record['x'][right, 0])/2
        result = np.column_stack((result, same, front, front*clock))
    result -= record['market'] @ result
    if case == 'J25':
        common = result
        # 群固有項は共通項への差分としてL2=1で縮約する。
        result = np.column_stack((common, *(common if record['group'] == g else np.zeros_like(common) for g in range(4))))
    require(np.isfinite(result).all(), 'thirty_nonfinite_features')
    return result.astype(np.float32)


def pack(records, case):
    """一方式の馬連行列と競走境界を構築し、2GiB上限を検査する。"""
    require(bool(records), 'thirty_empty_training')
    counts = np.asarray([len(r['market']) for r in records], dtype=np.int32)
    starts = np.cumsum(np.r_[0, counts[:-1]])
    groups = np.repeat(np.arange(len(records)), counts)
    first = matrix(records[0], case)
    x = np.empty((int(counts.sum()), first.shape[1]), dtype=np.float32)
    for start, count, record in zip(starts, counts, records):
        x[start:start+count] = matrix(record, case)
    data = {'x': x, 'starts': starts, 'counts': counts, 'groups': groups,
            'target': starts+np.asarray([r['winner'] for r in records]),
            'offset': np.log(np.concatenate([r['market'] for r in records])),
            'contexts': np.asarray([r['group'] for r in records]),
            'dates': np.asarray([np.datetime64(r['race_date'], 'D').astype(int) for r in records])}
    check_memory(LIMIT)
    return data


def probabilities(logits, starts, groups):
    """連結競走ごとに安定なsoftmaxと対数正規化定数を返す。"""
    maxima = np.maximum.reduceat(logits, starts)
    weights = np.exp(logits-maxima[groups])
    totals = np.add.reduceat(weights, starts)
    weights /= totals[groups]
    return weights, maxima+np.log(totals)


def training_scale(x):
    """5万ペアずつ二次モーメントを計算し、全float64行列を確保しない。"""
    total = np.zeros(x.shape[1])
    squares = np.zeros(x.shape[1])
    for start in range(0, len(x), 50000):
        block = x[start:start+50000].astype(np.float64)
        total += block.sum(axis=0)
        np.square(block, out=block)
        squares += block.sum(axis=0)
        check_memory(LIMIT)
    return np.maximum(np.sqrt(np.maximum(0, squares/len(x)-(total/len(x))**2)), 1e-5)


def objective(beta, data, case):
    """固定の減衰/群頑健目的を含む損失と解析勾配を返す。"""
    x, groups = data['x'], data['groups']
    logits = data['offset'].copy()
    for start in range(0, len(x), 50000):
        block = x[start:start+50000].astype(np.float64)
        logits[start:start+len(block)] += block @ beta
        check_memory(LIMIT)
    probs, norm = probabilities(logits, data['starts'], groups)
    losses = norm-logits[data['target']]
    nr = len(losses)
    weights = np.full(nr, 1/nr)
    if case == 'J27':
        weights = np.exp2((data['dates']-max(data['dates']))/365)
        weights /= weights.sum()
    if case == 'J29':
        contexts = data['contexts']
        present = np.unique(contexts)
        group_losses = np.asarray([losses[contexts == g].mean() for g in present])
        group_weights = softmax(group_losses/.25)
        loss = float(.25*(logsumexp(group_losses/.25)-np.log(len(present))))
        for g, weight in zip(present, group_weights):
            weights[contexts == g] = weight/int(np.sum(contexts == g))
    else:
        loss = float(weights @ losses)
    probs[data['target']] -= 1
    probs *= weights[groups]
    penalty = np.full(len(beta), .1)
    if case == 'J25':
        penalty[len(beta)//5:] = 1
    loss += float(penalty @ (beta*beta))/2
    gradient = penalty*beta
    for start in range(0, len(x), 50000):
        block = x[start:start+50000].astype(np.float64)
        gradient += block.T @ probs[start:start+len(block)]
        check_memory(LIMIT)
    return loss, gradient


def fit(records, case):
    """当月より前の教師と尺度だけで、一方式を学習する。

    Args:
        records: 時系列で当月開始日前に限定済みの競走。
        case: R1またはJ01〜J25/J27〜J29。
    Returns:
        dict: 固定方式、尺度、係数または木、学習最終日と最適化証跡。
    Raises:
        ResearchError: メモリ超過または最適化未収束。
    """
    data = pack(records, case)
    scale = training_scale(data['x'])
    data['x'] /= scale.astype(np.float32)
    artifact = {'case': case, 'scale': scale, 'trained_through': max(r['race_date'] for r in records),
                'train_races': len(records)}
    with threadpool_limits(limits=1):
        if case == 'J28':
            logits = data['offset'].copy()
            trees = []
            for _ in range(12):
                p, _ = probabilities(logits, data['starts'], data['groups'])
                target = -p
                target[data['target']] += 1
                hessian = np.maximum(p*(1-p), 1e-5)
                tree = DecisionTreeRegressor(max_depth=2, min_samples_leaf=200, random_state=241)
                tree.fit(data['x'], np.clip(target/hessian, -10, 10), sample_weight=hessian)
                logits += .05*tree.predict(data['x'])
                trees.append(tree)
                check_memory(LIMIT)
            artifact.update(trees=trees, optimizer={'success': True, 'trees': 12})
        else:
            result = minimize(objective, np.zeros(data['x'].shape[1]), args=(data, case), jac=True,
                              method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
            require(bool(result.success), 'thirty_optimizer_failed')
            artifact.update(coef=result.x, optimizer={'success': True, 'iterations': int(result.nit), 'objective': float(result.fun)})
    check_memory(LIMIT)
    return artifact


def fit_stack(past):
    """前月までのOOS正解組確率だけで、市場と29方式の混合重みを学ぶ。"""
    prior = np.zeros(30)
    prior[0] = 1
    if len(past) == 0:
        return {'case': 'J30', 'weights': prior, 'history_races': 0, 'cold_start': True}
    values = np.asarray(past, dtype=float)
    require(values.ndim == 2 and values.shape[1] == 30 and np.all(values > 0), 'thirty_stack_inputs')

    def stack_objective(weights):
        """単体のOOS正解確率の凸混合を正則化して最適化する。"""
        p = np.maximum(values @ weights, 1e-300)
        delta = weights-prior
        return float(-np.log(p).mean()+.001*(delta @ delta)/2), -(values/p[:, None]).mean(axis=0)+.001*delta

    result = minimize(stack_objective, prior, jac=True, method='SLSQP', bounds=[(0, 1)]*30,
                      constraints=[{'type': 'eq', 'fun': lambda w: w.sum()-1,
                                    'jac': lambda w: np.ones_like(w)}], options={'maxiter': 250, 'ftol': 1e-10})
    require(bool(result.success), 'thirty_stack_optimizer_failed')
    weights = np.maximum(result.x, 0)
    weights /= weights.sum()
    return {'case': 'J30', 'weights': weights, 'history_races': len(past), 'cold_start': False}


def confidence(past_losses):
    """過去OOSのJ01対市場損失差から当月固定の反映率を返す。"""
    return float(expit(-50*np.mean(past_losses))) if past_losses else .5


def predict(model, record, components=None):
    """結果を含まない公開特徴だけから全馬連の確率を返す。"""
    case = model['case']
    if case == 'M0':
        return record['market'].copy()
    if case == 'J26':
        p = predict(model['base'], record)
        return model['weight']*p+(1-model['weight'])*record['market']
    if case == 'J30':
        require(components is not None, 'thirty_missing_components')
        return model['weights'] @ np.asarray(components)
    x = matrix(record, case)/model['scale'].astype(np.float32)
    if case == 'J28':
        score = sum(.05*t.predict(x) for t in model['trees'])
    else:
        score = x @ model['coef']
    return softmax(np.log(record['market'])+score)
