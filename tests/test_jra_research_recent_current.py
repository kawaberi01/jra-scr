"""概要: S1の前日境界・欠測・公開直近枠・結果遮断・勾配を確認する。
作成日: 2026-10-27
入力: 合成前走、保存済み原本1件、合成係数。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_recent_current.py
注意事項: SQL・HTTP・実学習・既存成果物更新なし。
"""

from datetime import date, timedelta
from collections import Counter
import gzip
import io
import json

import numpy as np
import pytest

from jra_srb import jra_research_recent_current as model
from jra_srb.jra_research_artifacts import ROOT
from jra_srb.jra_research_contracts import ResearchError


def previous(**changes):
    """正常な合成前走を作る。"""
    return {'race_date': '2026-10-01', 'rank': 3, 'field_size': 10, 'surface': 0, 'distance': 1800, 'valid': True}|changes


def sample():
    """保存済み事前原本1件を返す。"""
    with gzip.open(ROOT/'artifacts/jra_research/forward_capture_20261025_v4/inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return json.loads(next(stream))


def fitted():
    """結果遮断を検証する24列の合成モデルを返す。"""
    return {'protocol': model.PROTOCOL, 'input_fields': list(model.FIELDS), 'recent_names': list(model.RECENT_NAMES),
            'trained_through': '2025-12-31', 'contexts': ['common'], 'scale': np.ones(24),
            'coef': np.arange(24, dtype=float).reshape(1, -1)/30}


def test_recent_definition_and_window():
    """相対着順・距離差・芝ダート・日数と180日境界を確認する。"""
    values, reason = model.recent_vector('2026-10-11', 1, 2000, previous())
    np.testing.assert_allclose(values, [7/9, .5, 0, 10/180, 0])
    assert reason == 'observed'
    day = date(2026, 10, 1)
    assert model.recent_vector((day+timedelta(days=180)).isoformat(), 0, 1800, previous())[1] == 'observed'
    assert model.recent_vector((day+timedelta(days=181)).isoformat(), 0, 1800, previous())[1] == 'outside_180d'


@pytest.mark.parametrize('prior', [None, previous(rank=None), previous(surface=None), previous(valid=False)])
def test_missing_is_explicit(prior):
    """未観測・異常・対象外を観測値0と混同しない。"""
    v, reason = model.recent_vector('2026-10-11', 0, 1800, prior)
    np.testing.assert_array_equal(v, [0, 0, 0, 0, 1])
    assert reason != 'observed'


@pytest.mark.parametrize('day', ['2026-10-01', '2026-09-30'])
def test_future_and_same_day_rejected(day):
    """同日または未来の結果を過去走として利用しない。"""
    with pytest.raises(ResearchError):
        model.recent_vector(day, 0, 1800, previous())


def test_capture_order_and_no_fallback_to_older_good_run():
    """最新の異常走を飛ばして古い好走へ差し替えない。"""
    obs = sample()
    row = obs['card']['runners'][0]
    row['official_recent_races'] = [
        {'source_date': '2026-10-01', 'source_course': '東京', 'surface': '芝', 'distance': 1800, 'finish_rank': 1, 'field_size': 10},
        {'source_date': '2026-10-10', 'source_course': '東京', 'surface': '芝', 'distance': 1800, 'finish_rank': None, 'field_size': 10}]
    r, provenance = model.from_capture(obs)
    assert provenance['reasons'][0] == 'invalid_previous_result' and r['recent'][0, 4] == 1
    row['official_recent_races'].reverse()
    rr, _ = model.from_capture(obs)
    np.testing.assert_array_equal(r['recent'], rr['recent'])


def test_result_and_legacy_history_firewall():
    """今回結果と元D0履歴を変えてもS1の確率は変わらない。"""
    r, _ = model.from_capture(sample())
    p = model.predict(fitted(), r)
    altered = r|{'winner': 'poison', 'payout_yen': 'poison', 'x': 'poison', 'horse_id': 'poison'}
    np.testing.assert_array_equal(p, model.predict(fitted(), altered))
    assert model.matrix(r).shape[1] == 24
    with pytest.raises(ResearchError):
        model.predict(fitted()|{'trained_through': r['race_date']}, r)


def test_training_gradient_and_roster_boundaries():
    """24列の訓練境界と解析勾配を数値差分で確認する。"""
    r, _ = model.from_capture(sample())
    data = model.pack([r|{'winner': i} for i in range(3)])
    width = len(r['market'])
    assert data['targets'].tolist() == [0, width+1, width*2+2]
    assert data['names'] == ['common']
    beta = np.linspace(-.02, .02, 24)
    analytic = model.base.core.objective(beta, data)[1]
    for i in (0, 13, 14, 18, 23):
        e = np.zeros(24)
        e[i] = 1e-5
        numeric = (model.base.core.objective(beta+e, data)[0]-model.base.core.objective(beta-e, data)[0])/2e-5
        assert analytic[i] == pytest.approx(numeric, abs=1e-7)


def history_fixture():
    """原本の出走集合に合成ID・前日以前イベントを付けた日別処理入力を返す。"""
    r, _ = model.from_capture(sample())
    n = len(r['horses'])
    days = (date.fromisoformat(r['race_date'])-date(2026, 10, 1)).days
    runners = [{'horse_no': str(int(h)), 'horse_id': str(1000000000+i),
                'history_features': {'horse_has_history': 1, 'days_since_last_scaled': days/365}}
               for i, h in enumerate(r['horses'])]
    card = {'race_id': r['race_id'], 'race_date': r['race_date'], 'inputs': {'runners': runners},
            'race': {'surface': 'turf', 'distance': 1800},
            'result': {'ranks_by_horse': {str(int(h)): i+1 for i, h in enumerate(r['horses'])},
                       'runner_statuses': {str(int(h)): {'abnormal_code': '0'} for h in r['horses']}}}
    latest = {row['horse_id']: previous(race_id='202610010501', rank=i+1, field_size=n) for i, row in enumerate(runners)}
    return r|{'winner': 0}, card, latest


def test_daily_update_after_features_and_current_result_ignored(monkeypatch):
    """当日結果の順位変更が同日の特徴へ入らず、全特徴後に状態更新される。"""
    import importlib
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    runner = importlib.import_module('run_jra_recent_current')
    r, card, latest = history_fixture()
    output = {}
    runner.prepare_day([card], latest, {r['race_id']: r}, output, Counter(), io.StringIO())
    a = output[r['race_id']]['recent']
    assert np.all(a[:, 4] == 0) and all(p['race_date'] == r['race_date'] for p in latest.values())
    r, card, latest = history_fixture()
    card['result']['ranks_by_horse'] = dict(zip(card['result']['ranks_by_horse'], reversed(range(1, len(r['horses'])+1)), strict=True))
    output = {}
    runner.prepare_day([card], latest, {r['race_id']: r}, output, Counter(), io.StringIO())
    np.testing.assert_array_equal(a, output[r['race_id']]['recent'])


def test_stale_stored_event_not_treated_as_latest(monkeypatch):
    """保存集計の前走間隔と違うイベントは欠測にし、古い走を採らない。"""
    import importlib
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    runner = importlib.import_module('run_jra_recent_current')
    r, card, latest = history_fixture()
    card['inputs']['runners'][0]['history_features']['days_since_last_scaled'] = 1/365
    output, ledger = {}, io.StringIO()
    runner.prepare_day([card], latest, {r['race_id']: r}, output, Counter(), ledger)
    assert output[r['race_id']]['recent'][0, 4] == 1
    assert json.loads(ledger.getvalue())['references'][0]['reason'] == 'stored_interval_mismatch'
