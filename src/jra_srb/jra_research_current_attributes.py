"""概要: 履歴を要求せず市場と当日属性から条件別補正を学習するS0。
作成日: 2026-10-25
入力: 市場確率、単勝PL、当日6属性、競馬場・芝ダート・距離・日付。
出力: 保存可能なS0モデルと全馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_current_attributes.py
注意事項: 研究専用。過去取得・SQL更新・既定モデル変更は行わない。
"""

from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from . import jra_research_market_chimera as core
from .jra_research_attribute_chimera import ATTRIBUTES, pair_values, sex_age_attributes
from .jra_research_chimera_thirty_features import pl_pairs
from .jra_research_contracts import horse_number
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

PROTOCOL = 'spec425-current-attributes-S0-v1'
FIELDS = ('race_id', 'race_date', 'course', 'surface', 'distance', 'horses', 'market', 'pl', 'attributes')


def clean(record):
    """推論で必要な現在情報だけを許可し、履歴と結果を遮断する。"""
    return {key: record[key] for key in FIELDS}


def matrix(record):
    """市場2列と属性12列を市場期待値で中心化した14列にする。"""
    r = clean(record)
    n = len(r['horses'])
    require(8 <= n <= 18 and len(set(r['horses'])) == n, 'S0_roster')
    require(1 <= int(r['course']) <= 10 and int(r['surface']) in (0, 1), 'S0_condition')
    q, pl = (np.asarray(r[key], dtype=float) for key in ('market', 'pl'))
    require(q.shape == pl.shape == (n*(n-1)//2,) and np.isfinite(q).all() and np.isfinite(pl).all()
            and min(q) > 0 and min(pl) > 0 and abs(q.sum()-1) < 1e-8 and abs(pl.sum()-1) < 1e-8, 'S0_market')
    a = np.asarray(r['attributes'], dtype=np.float32)
    require(a.shape == (n, 6) and np.isfinite(a).all()
            and np.all((a[:, 0] >= .2)&(a[:, 0] <= 1.5))
            and np.all((a[:, 1:3] == 0)|(a[:, 1:3] == 1))
            and np.all(a[:, 1]+a[:, 2] <= 1)
            and np.all((a[:, 3] >= .125)&(a[:, 3] <= 1))
            and np.all((a[:, 4] > 0)&(a[:, 4] <= 18/8))
            and np.all((a[:, 5] == 0)|(a[:, 5] == 1)), 'S0_attributes')
    x = np.column_stack((np.log(q), np.clip(np.log(pl/q), -10, 10), pair_values(a)))
    x -= q @ x
    return x.astype(np.float32)


def pack(records):
    """履歴行列を作らず、既存目的関数に渡す競走境界と条件行を作る。"""
    require(bool(records), 'S0_empty_training')
    counts = np.asarray([len(core.base.pairs(len(r['horses']))) for r in records], dtype=np.int32)
    starts = np.cumsum(np.r_[0, counts[:-1]])
    cc = [core.base.contexts(clean(r), 'C2') for r in records]
    numbers = Counter(c for names in cc for c in names)
    names = ['common']+sorted(c for c, count in numbers.items() if count >= core.base.MIN_CONTEXT_RACES)
    ids = {name: i for i, name in enumerate(names)}
    memberships = defaultdict(list)
    x = np.empty((int(counts.sum()), 14), dtype=np.float32)
    for i, (r, start, count, contexts) in enumerate(zip(records, starts, counts, cc, strict=True)):
        x[start:start+count] = matrix(r)
        for c in contexts:
            if c in ids:
                memberships[ids[c]].append(i)
    scale = core.training_scale(x)
    x /= scale.astype(np.float32)
    indices = {c: np.concatenate([np.arange(starts[i], starts[i]+counts[i], dtype=np.int32) for i in races])
               for c, races in memberships.items()}
    target = np.asarray([r['winner'] for r in records], dtype=np.int32)
    require(np.all((target >= 0)&(target < counts)), 'S0_target')
    check_memory(core.base.MEMORY_LIMIT)
    return {'x': x, 'counts': counts, 'starts': starts, 'groups': np.repeat(np.arange(len(records)), counts),
            'targets': starts+target, 'indices': indices, 'scale': scale, 'names': names,
            'context_counts': dict(numbers), 'nr': len(records),
            'offset': np.log(np.concatenate([r['market'] for r in records]))}


def fit(records):
    """指定済みの過去年境界でS0を一度学習する。"""
    data = pack(records)
    with threadpool_limits(limits=1):
        result = minimize(core.objective, np.zeros(len(data['names'])*14), args=(data,), jac=True,
                          method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'S0_optimizer')
    check_memory(core.base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': 'S0', 'scale': data['scale'], 'contexts': data['names'],
            'coef': result.x.reshape(len(data['names']), 14), 'context_counts': data['context_counts'],
            'attribute_names': list(ATTRIBUTES), 'input_fields': list(FIELDS),
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'train_races': len(records), 'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """学習期間後の現在情報だけで馬連確率を出す。"""
    require(fitted['protocol'] == PROTOCOL and fitted['input_fields'] == list(FIELDS), 'S0_model')
    r = clean(record)
    require(fitted['trained_through'] < r['race_date'], 'S0_future_training')
    beta = fitted['coef'][0].copy()
    for c in core.base.contexts(r, 'C2'):
        if c in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(c)]
    p = softmax(np.log(r['market'])+(matrix(r)/fitted['scale'].astype(np.float32)) @ beta)
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'S0_probability')
    return p


def from_capture(observation):
    """検算済み保存原本から履歴を参照せず現在情報を作る。

    Args:
        observation: spec420で出走集合・時刻・価格を検証した保存済み観測。
    Returns:
        S0の許可入力だけを持つ辞書。
    Raises:
        ResearchError: 属性、出走集合、価格などが不正な場合。
    """
    card = observation['card']
    runners = sorted([r for r in card['runners'] if r.get('status', 'active') == 'active'],
                     key=lambda r: int(horse_number(r['horse_no'])))
    horses = [horse_number(r['horse_no']) for r in runners]
    attrs = []
    for r in runners:
        frame = str(r.get('frame_no') or '').strip()
        missing = not frame
        require(missing or (frame.isdigit() and 1 <= int(frame) <= 8), 'S0_capture_frame')
        attrs.append([*sex_age_attributes(r['sex_age']), .5 if missing else int(frame)/8,
                      int(horse_number(r['horse_no']))/len(horses), int(missing)])
    prices = {}
    for bet, keys in [('win', [(h,) for h in horses]),
                      ('quinella', [(horses[a], horses[b]) for a, b in core.base.pairs(len(horses))])]:
        entries = observation['odds'][bet]
        values = {tuple(sorted(horse_number(h) for h in e['combination'])): float(e['odds']) for e in entries}
        require(len(values) == len(entries) and set(values) == set(keys), 'S0_capture_odds_roster')
        prices[bet] = np.asarray([values[key] for key in keys])
        require(np.isfinite(prices[bet]).all() and np.all(prices[bet] >= 1), 'S0_capture_odds')
    surface = card.get('surface')
    require(surface in ('turf', 'dirt', '芝', 'ダート', 0, 1), 'S0_capture_surface')
    q = 1/prices['quinella']
    r = {'race_id': observation['race_id'], 'race_date': observation['race_date'],
         'course': int(observation['race_id'][8:10]), 'surface': int(surface in ('dirt', 'ダート', 1)),
         'distance': int(str(card['distance']).replace(',', '')), 'horses': horses, 'attributes': np.asarray(attrs, dtype=np.float32),
         'market': q/q.sum(), 'pl': pl_pairs(1/prices['win'])}
    matrix(r)
    return r
