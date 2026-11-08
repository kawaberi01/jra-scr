"""概要: D0に履歴量・休養・条件変更による能力評価の相互作用を追加する。
作成日: 2026-10-24
入力: spec365の公開属性と15履歴特徴、市場、訓練時のみ正解ペア。
出力: QH/QR/QCの64列モデルと馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_quality_chimera.py --help
注意事項: 血統/調教/疲労の観測ではない。既使用過去の研究用。
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from . import jra_research_attribute_chimera as base
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

PROTOCOL = 'spec370-quality-interaction-chimera-v1'
CASES = ('QH', 'QR', 'QC')
clean = base.clean


def gate(record, case):
    """既存の前日特徴だけから、固定した信頼度の相互作用係数を返す。"""
    require(case in CASES, 'quality_unknown_case')
    x = np.asarray(record['x'], dtype=np.float32)
    require(np.isfinite(x).all() and np.all(x[:, 9] >= 0) and np.all(x[:, 10] >= 0)
            and np.all((x[:, 13] == 0)|(x[:, 13] == 1)), 'quality_invalid_history')
    if case == 'QH':
        n = np.expm1(5*x[:, 9].astype(float))
        return n/(n+5)
    if case == 'QR':
        return 1/(1+365*x[:, 10].astype(float)/90)
    return (1-x[:, 13].astype(float))*np.exp(-np.abs(x[:, 12].astype(float))/2)


def matrix(record, case):
    """D0の46列に能力9列×固定gateの対称ペア18列を加える。"""
    horse = np.asarray(record['x'], dtype=np.float32)
    gated = (horse[:, :9]*gate(record, case)[:, None]).astype(np.float32)
    out = np.column_stack((base.matrix(record, 'D0').astype(float), base.pair_values(gated).astype(float)))
    out -= np.asarray(record['market']) @ out
    require(out.shape[1] == 64 and np.isfinite(out).all(), 'quality_matrix_contract')
    return out.astype(np.float32)


def fit(records, case):
    """D0と同じ時系列教師・正則化で、追加相互作用だけを学習する。

    Args:
        records: 予測年より前の正解付き競走。
        case: QH/QR/QC。
    Returns:
        係数・尺度・条件件数・教師期間を含む保存辞書。
    Raises:
        ResearchError: 入力不整合、収束失敗、メモリ上限超過。
    """
    data = base.core.pack(records, 'H2')
    x = np.empty((len(data['x']), 64), dtype=np.float32)
    for r, start, count in zip(records, data['starts'], data['counts'], strict=True):
        x[start:start+count] = matrix(clean(r), case)
    data['scale'] = base.core.training_scale(x)
    x /= data['scale'].astype(np.float32)
    data['x'] = x
    check_memory(base.core.base.MEMORY_LIMIT)
    with threadpool_limits(limits=1):
        result = minimize(base.core.objective, np.zeros(len(data['names'])*64), args=(data,), jac=True,
            method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(result.success and np.isfinite(result.x).all(), 'quality_optimizer_failed')
    check_memory(base.core.base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': case, 'coef': result.x.reshape(-1, 64),
        'scale': data['scale'], 'contexts': data['names'], 'context_counts': data['context_counts'],
        'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
        'train_races': len(records), 'horse_features': list(base.core.base.FEATURES), 'attribute_names': list(base.ATTRIBUTES),
        'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """保存D0か追加モデルを、結果欄を除いた前日入力へ適用する。"""
    if fitted['protocol'] == base.PROTOCOL:
        require(fitted['case'] == 'D0', 'quality_reference_only_D0')
        return base.predict(fitted, clean(record))
    require(fitted['protocol'] == PROTOCOL and fitted['horse_features'] == list(base.core.base.FEATURES)
            and fitted['attribute_names'] == list(base.ATTRIBUTES), 'quality_model_contract')
    record = clean(record)
    require(fitted['trained_through'] < record['race_date'], 'quality_future_training')
    x = matrix(record, fitted['case'])/fitted['scale'].astype(np.float32)
    beta = fitted['coef'][0].copy()
    for name in base.core.base.contexts(record, 'C2'):
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    p = softmax(np.log(record['market'])+x @ beta)
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'quality_probability_contract')
    return p
