"""概要: H2に当日属性・連続距離・レース条件の共有効果を追加する。
作成日: 2026-10-24
入力: 同時点市場/15履歴特徴、当日の6馬属性と3競走条件フラグ。
出力: D0/D1/D2の保存モデルと馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_attribute_chimera.py --help
注意事項: 公開属性の歴史公表時点は未証明。結果/精算は推論へ渡さない。
"""

from __future__ import annotations

import numpy as np
import re
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from . import jra_research_market_chimera as core
from .jra_research_r1_live import require
from .jra_research_resources import check_memory


PROTOCOL = 'spec365-attribute-distance-chimera-v1'
CASES = ('D0', 'D1', 'D2')
ATTRIBUTES = ('age_scaled', 'female', 'gelding', 'frame_scaled', 'horse_position', 'frame_missing')


def sex_age_attributes(label):
    """公開の性齢文字列を正規化し、ひらがなの「せん」も騸馬として扱う。

    Args:
        label: 牡3、牝4、セ5、せん6/鹿などの公開文字列。
    Returns:
        年齢/10、牝フラグ、騸フラグ。
    Raises:
        ResearchError: 公開表記を解釈できない、年齢が範囲外の場合。
    Notes:
        既存の性別履歴フラグに欠落があっても、明示された性齢表記を使う。
    """
    match = re.match(r'^(牡|牝|セン|せん|セ|騸)(\d+)', str(label).strip())
    require(match is not None and 2 <= int(match[2]) <= 15, 'attribute_public_sex_age')
    return int(match[2])/10, int(match[1] == '牝'), int(match[1] in ('セン', 'せん', 'セ', '騸'))


def clean(record):
    """既存公開欄に属性/競走条件だけを追加し、結果と払戻を遮断する。"""
    return {**core.clean(record), 'attributes': record['attributes'], 'race_flags': record['race_flags']}


def pair_values(horse):
    """馬別の任意属性から対称ペアの平均/絶対差を作る。"""
    ij = core.base.pairs(len(horse))
    a, b = horse[ij[:, 0]], horse[ij[:, 1]]
    return np.column_stack(((a+b)/2, np.abs(a-b)))


def matrix(record, case):
    """属性と距離/競走条件の相互作用を市場期待値で中心化する。

    Args:
        record: 結果を除いた公開属性/履歴/時点市場。
        case: D0属性、D1連続距離、D2競走条件も加える構成。
    Returns:
        ペア順の有限float32行列。既存H2の34列を先頭に保持する。
    Raises:
        ResearchError: 属性形状/定義/欠測表現が不正な場合。
    """
    require(case in CASES, 'attribute_unknown_case')
    attributes = np.asarray(record['attributes'], dtype=np.float32)
    flags = np.asarray(record['race_flags'], dtype=np.float32)
    require(attributes.shape == (len(record['horses']), 6) and np.isfinite(attributes).all()
            and flags.shape == (3,) and np.all((flags == 0)|(flags == 1)), 'attribute_input_shape')
    require(np.all((attributes[:, 0] >= .2)&(attributes[:, 0] <= 1.5))
            and np.all((attributes[:, 1:3] == 0)|(attributes[:, 1:3] == 1))
            and np.all((attributes[:, 3] >= .125)&(attributes[:, 3] <= 1))
            and np.all((attributes[:, 4] > 0)&(attributes[:, 4] <= 18/8))
            and np.all((attributes[:, 5] == 0)|(attributes[:, 5] == 1)), 'attribute_invalid_public_value')
    components = [core.matrix(record, 'H2').astype(float), pair_values(attributes).astype(float)]
    if case in ('D1', 'D2'):
        distance = np.clip((int(record['distance'])-2000)/1000, -1.2, 1.6)
        hx = core.base.pair_matrix(record, list(range(15))).astype(float)
        components.append(hx*distance)
    if case == 'D2':
        hx = core.base.pair_matrix(record, list(range(9))).astype(float)
        components.extend(hx*value for value in flags)
    x = np.column_stack(components)
    x -= record['market'] @ x
    require(np.isfinite(x).all(), 'attribute_nonfinite_features')
    return x.astype(np.float32)


def pack(records, case):
    """H2の競走境界/条件群を再利用して追加入力の訓練内尺度を作る。"""
    data = core.pack(records, 'H2')
    x = np.empty((len(data['x']), matrix(clean(records[0]), case).shape[1]), dtype=np.float32)
    for r, start, count in zip(records, data['starts'], data['counts'], strict=True):
        x[start:start+count] = matrix(clean(r), case)
    data['x'] = x
    data['scale'] = core.training_scale(x)
    x /= data['scale'].astype(np.float32)
    check_memory(core.base.MEMORY_LIMIT)
    return data


def fit(records, case):
    """過去教師だけで当日属性/連続距離モデルを学習する。

    Args:
        records: 年境界を限定済みの教師。
        case: D0/D1/D2。
    Returns:
        入力定義、尺度、係数、訓練期間/件数、収束証跡を持つ辞書。
    Raises:
        ResearchError: 入力不正、最適化非収束、2GiB超過。
    """
    data = pack(records, case)
    with threadpool_limits(limits=1):
        result = minimize(core.objective, np.zeros(len(data['names'])*data['x'].shape[1]), args=(data,),
            jac=True, method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
    require(bool(result.success) and np.isfinite(result.x).all(), 'attribute_optimizer_failed')
    check_memory(core.base.MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': case, 'scale': data['scale'], 'contexts': data['names'],
        'coef': result.x.reshape(len(data['names']), -1), 'context_counts': data['context_counts'],
        'attribute_names': list(ATTRIBUTES), 'horse_features': list(core.base.FEATURES),
        'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
        'train_races': len(records), 'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}


def predict(fitted, record):
    """前日履歴と公開属性から推論し、未学習条件は親/共通係数へ戻す。"""
    require(fitted['protocol'] == PROTOCOL and fitted['attribute_names'] == list(ATTRIBUTES), 'attribute_model_contract')
    record = clean(record)
    require(fitted['trained_through'] < record['race_date'], 'attribute_future_training')
    x = matrix(record, fitted['case'])/fitted['scale'].astype(np.float32)
    beta = fitted['coef'][0].copy()
    for name in core.base.contexts(record, 'C2'):
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    p = softmax(np.log(record['market'])+x @ beta)
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9, 'attribute_invalid_probability')
    return p
