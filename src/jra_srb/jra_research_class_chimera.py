"""概要: 全場共有D0に訓練内の競走条件コード別係数を追加する研究モデル。
作成日: 2026-10-25
入力: D0公開特徴と3桁class_code、訓練時だけ正解。
出力: BCのクラス差分付き係数と馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_class_chimera.py --help
注意事項: 歴史公表時点未証明。年齢/性別限定・G1コードの追加ではない。
"""

from collections import Counter, defaultdict
import re

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from . import jra_research_attribute_chimera as base
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

PROTOCOL = 'spec400-D0-class-context-v1'


def normalize_code(value):
    """未設定000と不正/欠測を未知カテゴリにし、3桁コードはそのまま使う。"""
    text = str(value).strip()
    return text if re.fullmatch(r'\d{3}', text) and text != '000' else 'UNK'


def clean(record):
    """D0公開欄と正規化したコードだけを通し、結果/払戻を除く。"""
    return {**base.clean(record), 'class_code': normalize_code(record.get('class_code'))}


def pack(records):
    """既存D0行列に、訓練内100件以上のクラス差分の行集合を追加する。"""
    data = base.pack(records, 'D0')
    codes = [normalize_code(r.get('class_code')) for r in records]
    counts = Counter(codes)
    groups = defaultdict(list)
    for i, code in enumerate(codes):
        if code != 'UNK' and counts[code] >= 100:
            groups[code].append(i)
    for code, members in sorted(groups.items()):
        index = len(data['names'])
        data['names'].append('class:'+code)
        data['indices'][index] = np.concatenate([np.arange(data['starts'][i], data['starts'][i]+data['counts'][i], dtype=np.int32) for i in members])
        data['context_counts']['class:'+code] = counts[code]
    return data, dict(counts)


def fit(records):
    """既存D0と同じ目的関数でクラスによる特徴の効き方を追加学習する。"""
    data, counts = pack(records)
    with threadpool_limits(limits=1):
        result = minimize(base.core.objective, np.zeros(len(data['names'])*46), args=(data,), jac=True,
            method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(result.success and np.isfinite(result.x).all(), 'class_optimizer_failed')
    check_memory(base.core.base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': 'BC', 'scale': data['scale'], 'coef': result.x.reshape(-1, 46),
        'contexts': data['names'], 'context_counts': data['context_counts'], 'class_counts': counts,
        'attribute_names': list(base.ATTRIBUTES), 'horse_features': list(base.core.base.FEATURES),
        'train_races': len(records), 'trained_from': min(r['race_date'] for r in records),
        'trained_through': max(r['race_date'] for r in records), 'historical_publication_verified': False,
        'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """未知クラスを共有係数へ戻し、日付境界と結果遮断付きで推論する。"""
    require(fitted['protocol'] == PROTOCOL and fitted['attribute_names'] == list(base.ATTRIBUTES), 'class_model_contract')
    r = clean(record)
    require(fitted['trained_through'] < r['race_date'], 'class_future_training')
    x = base.matrix(r, 'D0')/fitted['scale'].astype(np.float32)
    names = list(base.core.base.contexts(r, 'C2'))+['class:'+r['class_code']]
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    p = softmax(np.log(r['market'])+x@beta)
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'class_probability_contract')
    return p
