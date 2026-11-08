"""概要: 条件別キメラの時間境界・勾配・少標本共有・非市場推論を検証する。
作成日: 2026-10-24
入力: 外部通信しない固定seedの人工競走。
出力: pytest結果。成功0、失敗は非0。
実行例: uv run --frozen --extra ml --extra dev pytest -q tests/test_jra_research_condition_chimera.py
注意事項: 人工データの一致は実レースの予測性能を保証しない。SQLアクセスなし。
"""

from datetime import date

import joblib
import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative

from jra_srb import jra_research_condition_chimera as m
from jra_srb.jra_research_contracts import ResearchError


def records(n=120):
    """時計評価が高い2頭を正解とする再現可能な人工教師を返す。"""
    rng = np.random.default_rng(350)
    out = []
    for i in range(n):
        x = rng.normal(size=(8, 15)).astype(np.float32)
        winners = tuple(sorted(np.argsort(-x[:, 0])[:2]))
        out.append({'race_id': str(i), 'race_date': '2023-01-01', 'course': 8, 'surface': 0,
                    'distance': 3000, 'horses': [f'{j:02d}' for j in range(1, 9)],
                    'x': x, 'winner': list(map(tuple, m.pairs(8))).index(winners)})
    return out


@pytest.fixture(scope='module')
def fitted():
    """条件係数を含む小さいモデルを1回だけ学習する。"""
    return m.fit(records(), 'C2')


def test_analytic_gradient():
    """非0係数で中心差分と解析勾配を照合する。"""
    data = m.pack(records(), 'C2', [0, 3])
    beta = np.random.default_rng(7).normal(0, .1, len(data['names'])*4)
    numerical = approx_derivative(lambda b: m.objective(b, data)[0], beta, method='3-point').ravel()
    np.testing.assert_allclose(m.objective(beta, data)[1], numerical, rtol=1e-5, atol=1e-7)


def test_prediction_ignores_outcomes_and_market(fitted):
    """結果・市場・払戻を入れ替えても確率を変えない。"""
    record = {**records(1)[0], 'race_date': '2024-01-01'}
    p = m.predict(fitted, record)
    changed = {**record, 'winner': -1, 'market': [np.nan], 'prices': [999], 'payout_yen': 99999}
    np.testing.assert_array_equal(p, m.predict(fitted, changed))
    assert p.sum() == pytest.approx(1)
    assert min(p) > 0
    report = m.forecast(fitted, changed)
    assert sum(r['top2_probability'] for r in report['horse_ranking']) == pytest.approx(2)


def test_future_training_rejected(fitted):
    """訓練最終日と同日以前の推論を拒否する。"""
    with pytest.raises(ResearchError, match='condition_future_training'):
        m.predict(fitted, records(1)[0])


def test_rare_context_falls_back(fitted):
    """未学習競馬場の差分を使用せず、共通と共有可能な親条件を使う。"""
    record = {**records(1)[0], 'race_date': '2024-01-01', 'course': 5}
    report = m.forecast(fitted, record)
    assert 'sd:0:4' in report['active_contexts']
    assert 'cs:5:0' in report['fallback_contexts']
    data = m.pack(records(99), 'C2', [0])
    assert data['names'] == ['common']


def test_condition_coefficient_changes_predictions(fitted):
    """条件差分を0にした対照と比較し、条件を飾り列にしていないことを確かめる。"""
    record = {**records(1)[0], 'race_date': '2024-01-01'}
    common = {**fitted, 'coef': fitted['coef'].copy()}
    common['coef'][1:] = 0
    assert not np.allclose(m.predict(fitted, record), m.predict(common, record))


def test_serialization_and_pair_permutation(fitted, tmp_path):
    """保存前後の一致と、出走馬の並べ替えに対するペア確率の対応を検査する。"""
    path = tmp_path/'model.joblib'
    joblib.dump(fitted, path)
    record = {**records(1)[0], 'race_date': '2024-01-01'}
    p = m.predict(fitted, record)
    np.testing.assert_array_equal(p, m.predict(joblib.load(path), record))
    order = np.arange(7, -1, -1)
    reversed_record = {**record, 'x': record['x'][order], 'horses': [record['horses'][i] for i in order]}
    a = {tuple(sorted(r['horses'])): r['probability'] for r in m.forecast(fitted, record)['pair_ranking']}
    b = {tuple(sorted(r['horses'])): r['probability'] for r in m.forecast(fitted, reversed_record)['pair_ranking']}
    for key in a:
        assert a[key] == pytest.approx(b[key], abs=1e-7)


def test_public_features_do_not_read_current_results():
    """履歴なしの公開特徴は対象競走の着順・実ペース・時計を参照しない。"""
    states = m.ConditionStates()
    race = {'surface': 0, 'distance': 3000, 'course': 8, 'ordinal': date(2024, 1, 1).toordinal(),
            'runners': [{'horse_id': str(i), 'age': 3} for i in range(8)]}
    x = states.condition_public(race)
    changed = {**race, 'pace': 9999, 'runners': [{**r, 'rank': 1, 'clock': 999} for r in race['runners']]}
    np.testing.assert_array_equal(x, states.condition_public(changed))
    assert np.all(x[:, 11] == 1)


def test_distance_season_and_ablation_boundaries():
    """距離帯/冬境界と、部品除去後の特徴数を検査する。"""
    assert [m.distance_band(v) for v in (1400, 1401, 1800, 1801, 2200, 2201, 2600, 2601)] == [0, 1, 1, 2, 2, 3, 3, 4]
    assert [m.season(f'2024-{month:02d}-01') for month in (12, 1, 2, 3, 6, 9)] == [0, 0, 0, 1, 2, 3]
    without = m.fit(records(20), 'C0', 'clock')
    assert len(without['scale']) == 24
    assert all(i not in without['columns'] for i in m.BLOCKS['clock'])
