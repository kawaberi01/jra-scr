"""概要: D0保存確率の強さと市場への縮約を、別期間で校正する。
作成日: 2026-10-25
入力: 正のD0/同時点市場の全馬連確率、校正時だけ正解と日付。
出力: K0/KT/KR/KC/KMの係数辞書と補正分布。
実行例: uv run --frozen --extra ml python scripts/run_jra_d0_calibration.py --help
注意事項: D0本体を再学習しない。既使用過去の探索用で購入判断ではない。
"""

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax

from .jra_research_r1_live import require

PROTOCOL = 'spec380-D0-fixed-calibration-v1'
CASES = ('K0', 'KT', 'KR', 'KC', 'KM')
FIT_FROM, FIT_THROUGH = '2023-01-01', '2023-08-31'


def clean(record):
    """校正推論に必要な日付と2確率だけを通し、結果を除く。"""
    return {k: record[k] for k in ('race_date', 'p', 'q')}


def validate(record):
    """同一形状の正規化済み正確率だけを受け入れる。"""
    p, q = np.asarray(record['p'], dtype=float), np.asarray(record['q'], dtype=float)
    require(p.ndim == 1 and p.shape == q.shape and len(p) >= 28 and np.isfinite(p).all()
            and np.isfinite(q).all() and min(p) > 0 and min(q) > 0
            and abs(p.sum()-1) < 1e-8 and abs(q.sum()-1) < 1e-8, 'D0_calibration_input')
    return p, q


def transform(case, parameters, record):
    """固定係数と公開確率だけで補正し、校正時の正解は参照しない。"""
    require(case in CASES, 'D0_calibration_case')
    p, q = validate(clean(record))
    if case == 'K0':
        return p.copy()
    if case == 'KT':
        require(.7 <= float(parameters['t']) <= 1.3, 'D0_calibration_parameter')
        return softmax(float(parameters['t'])*np.log(p))
    if case in ('KR', 'KC'):
        key = 'a' if case == 'KR' else ('high' if max(p) >= .2 else 'low')
        require(0 <= float(parameters[key]) <= 1, 'D0_calibration_parameter')
        return softmax(np.log(q)+float(parameters[key])*(np.log(p)-np.log(q)))
    weight = float(parameters['e'])
    require(0 <= weight <= .5, 'D0_calibration_parameter')
    return (1-weight)*p+weight*q


def optimize(records, case, key, bounds, identity):
    """等競走損失で1変数を最適化し、端点・恒等も比較する。"""
    def loss(value):
        """与えた固定係数による校正期間だけの平均正解損失を返す。"""
        parameters = {key: value} if case != 'KC' else {'high': value, 'low': value}
        return float(np.mean([-np.log(transform(case, parameters, r)[r['winner']]) for r in records]))
    result = minimize_scalar(loss, bounds=bounds, method='bounded', options={'xatol': 1e-8, 'maxiter': 200})
    require(result.success and np.isfinite(result.fun), 'D0_calibration_optimizer')
    options = [(float(value), loss(float(value))) for value in (identity, *bounds, result.x)]
    minimum = min(v[1] for v in options)
    value = min((v for v in options if v[1] <= minimum+1e-10), key=lambda v: abs(v[0]-identity))[0]
    return value


def fit(records, case):
    """指定された2023年1〜8月だけで固定候補の係数を校正する。

    Args:
        records: 校正期間の日付、p/q、正解ペアを持つ競走。
        case: K0/KT/KR/KC/KM。
    Returns:
        係数・教師ID・期間・件数を持つJSON互換辞書。
    Raises:
        ResearchError: 期間外、確率不正、最適化非収束。
    """
    require(case in CASES and bool(records) and all(FIT_FROM <= r['race_date'] <= FIT_THROUGH for r in records), 'D0_calibration_fit_dates')
    for r in records:
        p, _ = validate(r)
        require(0 <= r['winner'] < len(p), 'D0_calibration_label')
    params, group_counts = {}, {}
    if case == 'KT':
        params['t'] = optimize(records, case, 't', (.7, 1.3), 1.)
    elif case == 'KR':
        params['a'] = optimize(records, case, 'a', (0., 1.), 1.)
    elif case == 'KM':
        params['e'] = optimize(records, case, 'e', (0., .5), 0.)
    elif case == 'KC':
        for key in ('low', 'high'):
            subset = [r for r in records if (max(r['p']) >= .2) == (key == 'high')]
            group_counts[key] = len(subset)
            params[key] = optimize(subset, case, key, (0., 1.), 1.) if len(subset) >= 100 else 1.
    return {'protocol': PROTOCOL, 'case': case, 'parameters': params, 'group_counts': group_counts,
        'train_ids': [r['race_id'] for r in records], 'train_races': len(records),
        'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records)}


def predict(fitted, record):
    """校正末尾より後の公開確率へ適用し、結果欄を遮断する。"""
    require(fitted['protocol'] == PROTOCOL and fitted['trained_through'] < record['race_date'], 'D0_calibration_future_training')
    p = transform(fitted['case'], fitted['parameters'], clean(record))
    require(np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-8, 'D0_calibration_probability')
    return p
