"""概要: S0の履歴不要・結果遮断・原本変換・学習期間境界を確認する。
作成日: 2026-10-25
入力: 保存済み事前情報1件と合成モデル。
出力: pytestの成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_current_attributes.py
注意事項: 学習・SQL・HTTP・既存ファイル更新なし。
"""

import gzip
import json

import numpy as np
import pytest

from jra_srb import jra_research_current_attributes as model
from jra_srb.jra_research_artifacts import ROOT
from jra_srb.jra_research_contracts import ResearchError


def sample():
    """検算済み保存原本の最初の観測を返す。"""
    with gzip.open(ROOT/'artifacts/jra_research/forward_capture_20261025_v4/inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return json.loads(next(stream))


def fitted():
    """期間境界と14列だけを持つ合成モデルを返す。"""
    return {'protocol': model.PROTOCOL, 'input_fields': list(model.FIELDS), 'trained_through': '2025-12-31',
            'coef': np.arange(14, dtype=float).reshape(1, -1)/20, 'scale': np.ones(14), 'contexts': ['common']}


def test_history_and_result_not_required():
    """原本の過去走と結果を変更しても当日入力・推論は同一になる。"""
    obs = sample()
    a = model.from_capture(obs)
    assert set(a) == set(model.FIELDS) and model.matrix(a).shape[1] == 14
    for r in obs['card']['runners']:
        r['official_recent_races'] = 'poison'
    b = model.from_capture(obs)
    b.update(x='poison', winner='poison', payout_yen='poison')
    assert np.array_equal(model.predict(fitted(), a), model.predict(fitted(), b))


def test_future_training_rejected():
    """推論対象日まで学習したモデルを拒否する。"""
    r = model.from_capture(sample())
    f = fitted()|{'trained_through': r['race_date']}
    with pytest.raises(ResearchError):
        model.predict(f, r)


def test_incomplete_prices_rejected():
    """全ペアが揃わない価格を補完せず拒否する。"""
    obs = sample()
    obs['odds']['quinella'].pop()
    with pytest.raises(ResearchError):
        model.from_capture(obs)


def test_training_boundary_and_gradient():
    """履歴なし教師の境界・正解位置と14列の解析勾配を検算する。"""
    r = model.from_capture(sample())
    records = [r|{'winner': i % len(r['market'])} for i in range(3)]
    data = model.pack(records)
    assert data['names'] == ['common']
    assert data['x'].shape == (len(r['market'])*3, 14)
    assert data['targets'].tolist() == [i*len(r['market'])+i for i in range(3)]
    beta = np.linspace(-.02, .03, 14)
    analytic = model.core.objective(beta, data)[1]
    for i in (0, 1, 2, 7, 13):
        delta = np.zeros(14)
        delta[i] = 1e-5
        numeric = (model.core.objective(beta+delta, data)[0]-model.core.objective(beta-delta, data)[0])/2e-5
        assert analytic[i] == pytest.approx(numeric, abs=1e-7)
