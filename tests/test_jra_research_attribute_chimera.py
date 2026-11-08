"""概要: 公開属性追加の結合・連続距離・結果遮断・勾配を検査する。
作成日: 2026-10-24
入力: 人工公開カードと固定seedの市場/履歴特徴。
出力: pytest結果。
実行例: uv run --frozen --extra ml --extra dev pytest -q tests/test_jra_research_attribute_chimera.py
注意事項: SQL/HTTP/実購入なし。合成値は性能の証明ではない。
"""

import importlib.util
from pathlib import Path

import joblib
import numpy as np
import pytest

from jra_srb import jra_research_attribute_chimera as m
from jra_srb.jra_research_contracts import ResearchError
from test_jra_research_market_chimera import records as base_records


def records(n=20):
    """枠欠測を明示した6公開属性を人工教師に追加する。"""
    rows = base_records(n)
    for r in rows:
        r['attributes'] = np.array([[.3, i % 2, 0, .5, (i+1)/8, 1] for i in range(8)], dtype=np.float32)
        r['race_flags'] = np.array([0, 1, 0], dtype=np.float32)
    return rows


@pytest.mark.parametrize('case,width', [('D0', 46), ('D1', 76), ('D2', 130)])
def test_shapes_save_firewall_and_date(case, width, tmp_path):
    """入力次元、保存後一致、結果遮断と訓練境界を検査する。"""
    rows = records()
    assert m.matrix(rows[0], case).shape == (28, width)
    fitted = m.fit(rows, case)
    path = tmp_path/f'{case}.joblib'
    joblib.dump(fitted, path)
    r = {**rows[0], 'race_date': '2023-01-01'}
    p = m.predict(fitted, r)
    np.testing.assert_array_equal(p, m.predict(joblib.load(path), {**r, 'winner': -1, 'payout_yen': -999}))
    assert min(p) > 0 and p.sum() == pytest.approx(1)
    with pytest.raises(ResearchError, match='attribute_future_training'):
        m.predict(fitted, rows[0])


def test_continuous_distance_shares_nearby_conditions():
    """距離帯境界でも連続距離の列が滑らかに変わることを確認する。"""
    r = records(1)[0]
    a = m.matrix({**r, 'distance': 2600}, 'D1')
    b = m.matrix({**r, 'distance': 2601}, 'D1')
    c = m.matrix({**r, 'distance': 2602}, 'D1')
    np.testing.assert_allclose(b-a, c-b, atol=1e-6)
    assert not np.array_equal(a[:, 46:], b[:, 46:])


def test_additional_feature_gradient():
    """新しい属性/距離列を含む行列で解析勾配を数値差分照合する。"""
    data = m.pack(records(20), 'D2')
    b = np.random.default_rng(365).normal(0, .02, len(data['names'])*data['x'].shape[1])
    analytic = m.core.objective(b, data)[1]
    for i in (0, 35, 45, 60, 100, 129):
        e = np.zeros_like(b)
        e[i] = 1e-5
        numeric = (m.core.objective(b+e, data)[0]-m.core.objective(b-e, data)[0])/2e-5
        assert analytic[i] == pytest.approx(numeric, abs=1e-7)


def test_invalid_public_age_and_race_flag_rejected():
    """未知/不正属性を観測済みとして推論しない。"""
    r = records(1)[0]
    r['attributes'][0, 0] = 0
    with pytest.raises(ResearchError, match='attribute_invalid_public_value'):
        m.matrix(r, 'D0')


def test_public_card_join_and_explicit_missing_frame(monkeypatch):
    """カードの逆順から馬番で結合し、欠測枠を観測枠と区別する。"""
    import importlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    runner = importlib.import_module('run_jra_attribute_chimera')
    source = {'inputs': {'runners': [
        {'horse_no': '2', 'sex_age': 'せん4/鹿', 'frame_no': None, 'history_features': {'age_scaled': .4, 'sex_female': 0,
            'sex_gelding': 1, 'sex_male': 0, 'is_newcomer': 0, 'is_maiden': 1, 'is_open_or_stakes': 0}},
        {'horse_no': '1', 'sex_age': '牝3', 'frame_no': 1, 'history_features': {'age_scaled': .3, 'sex_female': 1,
            'sex_gelding': 0, 'sex_male': 0, 'is_newcomer': 0, 'is_maiden': 1, 'is_open_or_stakes': 0}},
    ]}}
    attrs, flags, count = runner.public_attributes(source, ['01', '02'])
    np.testing.assert_allclose(attrs[:, 0], [.3, .4])
    np.testing.assert_allclose(attrs[:, 3], [.125, .5])
    np.testing.assert_array_equal(attrs[:, 5], [0, 1])
    np.testing.assert_array_equal(flags, [0, 1, 0])
    assert count == 1
    source['inputs']['runners'][0]['history_features']['is_maiden'] = 0
    with pytest.raises(ResearchError, match='attribute_card_race_flags_disagree'):
        runner.public_attributes(source, ['01', '02'])


def test_public_gelding_spelling_and_unknown_legacy_flags(monkeypatch):
    """「せん」表記の公開事実を使い、旧フラグ全0を牡と誤解しない。"""
    import importlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    runner = importlib.import_module('run_jra_attribute_chimera')
    h = {'age_scaled': .6, 'sex_female': 0, 'sex_gelding': 0, 'sex_male': 0,
         'is_newcomer': 0, 'is_maiden': 0, 'is_open_or_stakes': 1}
    source = {'inputs': {'runners': [{'horse_no': '1', 'frame_no': 1, 'sex_age': 'せん6/鹿', 'history_features': h}]}}
    attrs, _, _ = runner.public_attributes(source, ['01'])
    np.testing.assert_allclose(attrs[0, :3], [.6, 0, 1])
    for label in ('セ6', 'セン6', 'せん6/鹿', '騸6'):
        assert m.sex_age_attributes(label) == (.6, 0, 1)
    with pytest.raises(ResearchError, match='attribute_public_sex_age'):
        m.sex_age_attributes('不明')
    source['inputs']['runners'][0]['sex_age'] = 'せん11/鹿'
    source['inputs']['runners'][0]['history_features']['age_scaled'] = 1.
    attrs, _, _ = runner.public_attributes(source, ['01'])
    assert attrs[0, 0] == pytest.approx(1.1)
