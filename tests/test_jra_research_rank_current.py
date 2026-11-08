"""概要: S2の純順位目的・負例境界・勾配・結果遮断・日単位区間を確認する。
作成日: 2026-11-05
入力: 保存原本1件と合成教師/係数。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_rank_current.py
注意事項: SQL・HTTP・実学習・既存成果物更新なし。
"""

import gzip
import json

import numpy as np
import pytest

from jra_srb import jra_research_rank_current as model
from jra_srb.jra_research_artifacts import ROOT
from jra_srb.jra_research_contracts import ResearchError


def record():
    """保存原本からS0と同じ入力だけを作る。"""
    with gzip.open(ROOT/'artifacts/jra_research/forward_capture_20261025_v4/inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return model.base.from_capture(json.loads(next(stream)))


def fitted():
    """スコア契約と入力境界を確認する合成14列モデルを返す。"""
    return {'protocol': model.PROTOCOL, 'input_fields': list(model.base.FIELDS), 'output_kind': 'rank_score_not_probability',
            'trained_through': '2025-12-31', 'scale': np.ones(14), 'contexts': ['common'], 'coef': np.zeros((1, 14))}


def test_market_negative_selection_and_race_weights():
    """市場上位の正解除外と、4/5負例でも競走重みが等しいことを確認する。"""
    r = record()
    order = np.argsort(-r['market'], kind='stable')
    data = model.pack([r|{'winner': int(order[0])}, r|{'winner': int(order[-1])}])
    assert len(data['x']) == 9
    assert data['weights'][:4].sum() == pytest.approx(.5) and data['weights'][4:].sum() == pytest.approx(.5)
    assert set(data['negative'][:4]) == set(map(int, order[1:5]))
    assert not np.any(data['positive'] == data['negative'])


def test_no_cross_entropy_term():
    """対比較重みを0にするとCEが残らず、ゼロ係数の損失と勾配が0になる。"""
    data = model.pack([record()|{'winner': 0}])
    data['weights'][:] = 0
    loss, gradient = model.objective(np.zeros(len(data['names'])*14), data)
    assert loss == 0 and np.all(gradient == 0)


def test_context_gradient_and_scale_reuse():
    """条件教師数閾値を満たす合成教師で全係数の勾配とS0尺度を照合する。"""
    r = record()
    records = [r|{'winner': i % len(r['market'])} for i in range(100)]
    data = model.pack(records)
    base = model.base.pack(records)
    assert np.array_equal(data['scale'], base['scale']) and data['names'] == base['names']
    assert len(data['names']) > 1
    beta = np.linspace(-.03, .03, len(data['names'])*14)
    analytic = model.objective(beta, data)[1]
    for i in [0, 1, 13, 14, len(beta)-1]:
        delta = np.zeros_like(beta)
        delta[i] = 1e-5
        numeric = (model.objective(beta+delta, data)[0]-model.objective(beta-delta, data)[0])/2e-5
        assert analytic[i] == pytest.approx(numeric, abs=1e-7)


def test_output_is_score_and_results_ignored():
    """ゼロ補正はlog市場を返し、結果・履歴を入力してもスコアを変えない。"""
    r = record()
    values = model.scores(fitted(), r)
    np.testing.assert_array_equal(values, np.log(r['market']))
    np.testing.assert_array_equal(values, model.scores(fitted(), r|{'winner': 'poison', 'x': 'poison', 'payout_yen': 'poison'}))
    assert np.all(values < 0) and values.sum() != pytest.approx(1)
    with pytest.raises(ResearchError):
        model.scores(fitted()|{'trained_through': r['race_date']}, r)


def test_cluster_intervals_preserve_same_day_difference():
    """同日をまとめた固定差では区間が点になり、日付やレース不一致を拒否する。"""
    a = [{'race_id': str(i), 'race_date': f'2025-01-0{i//2+1}', 'hit': 1, 'paid_yen': 200} for i in range(4)]
    b = [r|{'hit': 0, 'paid_yen': 0} for r in a]
    ci = model.comparison_ci(a, b)
    assert ci['hit_rate_difference_ci95'] == [1, 1] and ci['roi_difference_pp_ci95'] == [200, 200]
    with pytest.raises(ResearchError):
        model.comparison_ci(a, list(reversed(b)))
