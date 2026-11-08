"""概要: S0に定義を共有した直近走5特徴を加える研究用S1を提供する。
作成日: 2026-10-27
入力: S0の市場/当日属性/競走条件と、前日以前180日以内の直近走。
出力: S1係数、全馬連確率、欠測を明示した馬特徴。
実行例: uv run --frozen --extra ml python scripts/run_jra_recent_current.py
注意事項: 研究専用。既定変更・外部取得・SQL・購入なし。
"""

from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from . import jra_research_current_attributes as base
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

PROTOCOL = 'spec430-recent-current-S1-v1'
RECENT_NAMES = ('finish_fraction', 'distance_change', 'same_surface', 'rest_180', 'recent_missing')
FIELDS = (*base.FIELDS, 'recent')


def recent_vector(day, surface, distance, previous):
    """最新走を5特徴へ変換し、未観測・対象外は欠測として返す。

    Args:
        day: 予測対象日のISO日付。
        surface: 今回の芝0/ダート1。
        distance: 今回の距離m。
        previous: 日付/着順/頭数/距離/芝ダートを持つ最新走、またはNone。
    Returns:
        float32の5値と採用/欠測理由。未来・同日はエラー。
    """
    missing = np.asarray([0, 0, 0, 0, 1], dtype=np.float32)
    if previous is None:
        return missing, 'unobserved'
    days = (date.fromisoformat(day)-date.fromisoformat(previous['race_date'])).days
    require(days > 0, 'S1_future_or_same_day_history')
    if days > 180:
        return missing, 'outside_180d'
    if previous.get('surface') not in (0, 1):
        return missing, 'unsupported_previous_surface'
    n, rank, dist = (previous.get(k) for k in ('field_size', 'rank', 'distance'))
    if not (isinstance(n, int) and isinstance(rank, int) and 2 <= n <= 18 and 1 <= rank <= n
            and isinstance(dist, int) and 800 <= dist <= 4000 and previous.get('valid', True)):
        return missing, 'invalid_previous_result'
    return np.asarray([(n-rank)/(n-1), np.clip((int(distance)-dist)/400, -3, 3),
                       float(surface == previous['surface']), days/180, 0], dtype=np.float32), 'observed'


def clean(record):
    """今回結果や元履歴15列を通さず、S1の入力だけを取り出す。"""
    return {key: record[key] for key in FIELDS}


def matrix(record):
    """S0の14列に直近走10ペア列を追加し、市場期待値で中心化する。"""
    r = clean(record)
    recent = np.asarray(r['recent'], dtype=np.float32)
    require(recent.shape == (len(r['horses']), 5) and np.isfinite(recent).all(), 'S1_recent_shape')
    require(np.all((recent[:, 0] >= 0)&(recent[:, 0] <= 1))
            and np.all(np.abs(recent[:, 1]) <= 3)
            and np.all((recent[:, 2] == 0)|(recent[:, 2] == 1))
            and np.all((recent[:, 3] >= 0)&(recent[:, 3] <= 1))
            and np.all((recent[:, 4] == 0)|(recent[:, 4] == 1))
            and np.all(recent[recent[:, 4] == 1, :4] == 0), 'S1_recent_value')
    x = np.column_stack((base.matrix(r), base.pair_values(recent))).astype(float)
    x -= r['market'] @ x
    return x.astype(np.float32)


def pack(records):
    """S0の競走境界・条件群を使い、尺度を24列の教師内だけで作る。"""
    data = base.pack(records)
    x = np.empty((len(data['x']), 24), dtype=np.float32)
    for r, start, count in zip(records, data['starts'], data['counts'], strict=True):
        x[start:start+count] = matrix(r)
    data['x'] = x
    data['scale'] = base.core.training_scale(x)
    x /= data['scale'].astype(np.float32)
    check_memory(base.core.base.MEMORY_LIMIT)
    return data


def fit(records):
    """年境界を限定した教師だけで24列のS1を学習する。"""
    data = pack(records)
    with threadpool_limits(limits=1):
        result = minimize(base.core.objective, np.zeros(len(data['names'])*24), args=(data,), jac=True,
                          method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'S1_optimizer')
    check_memory(base.core.base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': 'S1', 'scale': data['scale'], 'contexts': data['names'],
            'coef': result.x.reshape(len(data['names']), 24), 'context_counts': data['context_counts'],
            'input_fields': list(FIELDS), 'recent_names': list(RECENT_NAMES),
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'train_races': len(records), 'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """現在情報と直近走だけから馬連確率を生成する。"""
    require(fitted['protocol'] == PROTOCOL and fitted['input_fields'] == list(FIELDS)
            and fitted['recent_names'] == list(RECENT_NAMES), 'S1_model_contract')
    r = clean(record)
    require(fitted['trained_through'] < r['race_date'], 'S1_future_training')
    beta = fitted['coef'][0].copy()
    for name in base.core.base.contexts(r, 'C2'):
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    p = softmax(np.log(r['market'])+(matrix(r)/fitted['scale'].astype(np.float32)) @ beta)
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'S1_probability')
    return p


def from_capture(observation):
    """公式直近枠の最新日付を使い、馬IDなしでS1入力を作る。"""
    r = base.from_capture(observation)
    lookup = {base.horse_number(row['horse_no']): row for row in observation['card']['runners']
              if row.get('status', 'active') == 'active'}
    recent, reasons, references = [], [], []
    for horse in r['horses']:
        slots = [s for s in lookup[horse].get('official_recent_races', []) if s.get('source_date')]
        require(all(s['source_date'] < r['race_date'] for s in slots), 'S1_capture_future_history')
        slot = max(slots, key=lambda s: s['source_date']) if slots else None
        previous = None
        if slot is not None:
            surface = {'芝': 0, 'ダート': 1, 'turf': 0, 'dirt': 1}.get(slot.get('surface'))
            previous = {'race_date': slot['source_date'], 'surface': surface, 'distance': slot.get('distance'),
                        'rank': slot.get('finish_rank'), 'field_size': slot.get('field_size'),
                        'valid': slot.get('source_course') in ('札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉')}
        values, reason = recent_vector(r['race_date'], r['surface'], r['distance'], previous)
        recent.append(values)
        reasons.append(reason)
        references.append(previous)
    return r|{'recent': np.asarray(recent, dtype=np.float32)}, {'reasons': reasons, 'previous': references}
