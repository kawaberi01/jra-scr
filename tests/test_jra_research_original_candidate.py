"""概要: 元候補の固定版推論・原型等価性・入力拒否・係数非依存を検証する。
作成日: 2026-10-23
入力: 合成の43履歴/12時計特徴と既存固定モデル、tmp_path。
出力: pytest結果。外部通信・DB・学習・実購入なし。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_original_candidate.py
注意事項: 合成入力の技術確認であり独立性能評価ではない。
"""

from copy import deepcopy
from itertools import combinations
import json
import sqlite3

import httpx
import numpy as np
import pytest

from jra_srb import jra_research_original_candidate as candidate
from jra_srb.jra_history_dataset import FEATURE_NAMES
from jra_srb.jra_research_contracts import ResearchError


def envelope(name='J23', day='2026-11-01', course='tokyo'):
    """来歴を合成と明記した8頭の結果なし入力を返す。"""
    horses = [f'{i:02d}' for i in range(1, 9)]
    pairs = list(combinations(horses, 2))
    result = {'schema': candidate.SCHEMA, 'candidate': name,
              'race_id': day.replace('-', '') + candidate.COURSES[course] + '01',
              'race_date': day, 'course': course, 'race_no': 1,
              'source': {'generator': 'synthetic_test_fixture', 'history_before': day,
                         'history_policy': 'strictly_before_target_day', 'input_sha256': {'synthetic': 'a' * 64},
                         'publication_verified': False, 'card_verified': False}}
    if name == 'J23':
        result['payload'] = {'horses': horses, 'x_horses': list(horses),
            'x': (np.arange(96).reshape(8, 12) / 1000).tolist(),
            'features_race_date': day, 'feature_definition_sha256': 'b' * 64,
            'start_at': day + 'T12:00:00+09:00', 'win_announced_at': day + 'T11:30:00+09:00',
            'quinella_announced_at': day + 'T11:30:00+09:00',
            'win': [{'horse_no': h, 'odds': 8.} for h in horses],
            'quinella': [{'horses': list(k), 'odds': 30.} for k in pairs]}
    else:
        h = {k: 0. for k in FEATURE_NAMES}
        h.update(age_scaled=.3, weight_carried_scaled=.87, horse_win_rate=.08,
                 horse_top3_rate=.25, horse_finish_strength=.5)
        result['payload'] = {'race': {'course': course, 'surface': 'turf', 'distance': 1600,
                                      'start_at': day + 'T12:00:00+09:00'},
            'inputs': {'history_as_of': day + 'T00:00:00+09:00',
                'runners': [{'horse_no': k, 'history_features': dict(h, horse_log_starts=float(int(k)) / 5,
                    horse_win_rate=.04 + int(k) / 100, horse_top3_rate=.2 + int(k) / 100,
                    weight_carried_scaled=.8 + int(k) / 100, age_scaled=.2 + int(k) / 100)} for k in horses],
                'odds': {'T-30m': {
                    'win': {'announced_at': day + 'T11:30:00+09:00', 'horses': [
                        {'horse_no': k, 'odds': 8., 'status': 'numeric'} for k in horses]},
                    'quinella': {'announced_at': day + 'T11:30:00+09:00', 'pairs': [
                        {'horse_no_1': k[0], 'horse_no_2': k[1], 'odds': 30., 'status': 'numeric'} for k in pairs]}}}}}
    return result


@pytest.fixture(scope='module')
def frozen_models():
    """元SHAを検証した2固定版を1回だけ読む。"""
    contracts = candidate.registry()
    return contracts, {name: candidate.load_model(name, contracts[name]) for name in ('J23', 'V110')}


@pytest.fixture
def isolated(monkeypatch, frozen_models):
    """固定モデルを再利用し、DB/HTTP/fitへ到達したら失敗させる。"""
    contracts, models = frozen_models
    monkeypatch.setattr(candidate, 'registry', lambda: contracts)
    monkeypatch.setattr(candidate, 'load_model', lambda name, contract: models[name])
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(httpx, 'get', forbidden)
    monkeypatch.setattr(candidate.legacy('jra_second_ten_model'), 'fit_suite', forbidden)
    return models


def forbidden(*args, **kwargs):
    """禁止した取得・学習・補正経路への到達を検出する。"""
    raise AssertionError('forbidden_side_effect')


@pytest.mark.parametrize('name', ['J23', 'V110'])
def test_result_and_later_odds_do_not_change_reference(name, isolated):
    """対象結果や後のオッズを加えても全ペア確率・選択・実購入0は変わらない。"""
    value = envelope(name)
    before = candidate.predict(value, name)
    value['result'] = {'ranks': 'arbitrary', 'payout': 999999}
    value['payload']['result'] = {'winner': '08', 'payout': 999999}
    if name == 'V110':
        value['payload']['inputs']['odds']['T-10m'] = {'bad': 'ignored'}
    after = candidate.predict(value, name)
    assert before['pairs'] == after['pairs'] and before['chosen'] == after['chosen']
    assert len(before['pairs']) == 28
    assert before['stake_yen'] == 0 and before['actual_tickets'] == []
    assert not before['performance_eligible'] and not before['adopted']


def test_v110_matches_existing_explicit_forecast(isolated):
    """既存の明示V110予測と全確率・最大1点が一致する。"""
    value = envelope('V110')
    race = deepcopy(value['payload'])
    race.update(race_id=value['race_id'], race_date=value['race_date'])
    baseline = candidate.legacy('score_jra_second_ten').forecast(isolated['V110'], race, 'V110')
    actual = candidate.predict(value, 'V110')
    np.testing.assert_array_equal([r['probability'] for r in actual['pairs']], list(baseline['probabilities'].values()))
    assert (actual['chosen']['horses'] if actual['chosen'] else None) == (
        baseline['ticket']['key'].split('-') if baseline['ticket'] else None)


def test_j23_november_matches_original_without_monthly_coefficients(isolated, monkeypatch):
    """11月の原型が補正係数を使わず旧J23部分と完全一致する。"""
    from jra_srb import jra_research_j23_live as live
    from jra_srb import jra_research_j23_policy as policy
    value = envelope()
    raw = value['payload']
    keys = list(combinations(raw['horses'], 2))
    market = 1 / np.full(28, 30.)
    market /= market.sum()
    record = {'x': np.asarray(raw['x'], dtype=np.float32), 'addition': np.empty((8, 0)),
              'basic': np.empty((8, 0)), 'styles': np.zeros(8), 'density': 0., 'group': 0,
              'market': market, 'pl': live.features.pl_pairs(np.full(8, 1 / 8))}
    parameters = policy.monthly_parameters({'2026-07': [], '2026-08': [], '2026-09': []}, '2026-10')
    baseline = live.score(isolated['J23'], record, keys, np.full(28, 30.), parameters)
    monkeypatch.setattr(policy, 'monthly_parameters', forbidden)
    monkeypatch.setattr(live, 'load_frozen', forbidden)
    monkeypatch.setattr(live, 'monthly_parameters', forbidden)
    actual = candidate.predict(value, 'J23')
    assert all(
        a['probability'] == b['probability'] and a['horses'] == b['horses']
        for a, b in zip(actual['pairs'], baseline['pairs'], strict=True))
    assert actual['chosen']['horses'] == baseline['chosen']['horses']


def test_history_mapping_is_by_name_and_rejects_bad_columns():
    """43列の順序変更は名前で対応し、欠測・重複・非有限値は拒否する。"""
    names = list(FEATURE_NAMES)
    values = [float(i) for i in range(43)]
    assert candidate.named_history(names, values) == candidate.named_history(names[::-1], values[::-1])
    for bad_names, bad_values in [(names[:-1], values[:-1]), ([names[0]] * 43, values),
                                  (names, [float('nan')] * 43)]:
        with pytest.raises(ResearchError):
            candidate.named_history(bad_names, bad_values)


@pytest.mark.parametrize('change', ['pair_missing', 'pair_duplicate', 'horse_order', 'x_shape', 'nan',
                                    'time_late', 'time_naive', 'date', 'history', 'identity', 'x_order'])
def test_j23_invalid_input_is_rejected(change, isolated):
    """市場・特徴順・時刻・同定・未来履歴の不正を拒否する。"""
    value = envelope()
    raw = value['payload']
    if change == 'pair_missing': raw['quinella'].pop()
    elif change == 'pair_duplicate': raw['quinella'].append(raw['quinella'][0])
    elif change == 'horse_order': raw['horses'].reverse()
    elif change == 'x_shape': raw['x'].pop()
    elif change == 'nan': raw['x'][0][0] = float('nan')
    elif change == 'time_late': raw['win_announced_at'] = '2026-11-01T11:31:00+09:00'
    elif change == 'time_naive': raw['start_at'] = '2026-11-01T12:00:00'
    elif change == 'date': value['race_date'] = '2026-08-30'
    elif change == 'history': value['source']['history_latest_date'] = value['race_date']
    elif change == 'identity': value['race_id'] = '202611010601'
    elif change == 'x_order': raw['x_horses'].reverse()
    with pytest.raises(ResearchError): candidate.predict(value, 'J23')


@pytest.mark.parametrize('change', ['missing', 'unknown', 'horse_duplicate', 'pair_duplicate', 'late', 'cutoff'])
def test_v110_invalid_input_is_rejected(change, isolated):
    """V110の履歴列と完全市場の入力契約を守る。"""
    value = envelope('V110')
    inp = value['payload']['inputs']
    if change == 'missing': inp['runners'][0]['history_features'].pop(FEATURE_NAMES[0])
    elif change == 'unknown': inp['runners'][0]['history_features']['unknown'] = 0
    elif change == 'horse_duplicate': inp['runners'].append(inp['runners'][0])
    elif change == 'pair_duplicate': inp['odds']['T-30m']['quinella']['pairs'].append(inp['odds']['T-30m']['quinella']['pairs'][0])
    elif change == 'late': inp['odds']['T-30m']['quinella']['announced_at'] = '2026-11-01T11:31:00+09:00'
    elif change == 'cutoff': inp['history_as_of'] = '2026-11-01T10:00:00+09:00'
    with pytest.raises(ResearchError): candidate.predict(value, 'V110')


@pytest.mark.parametrize('name,day,course', [('V110', '2026-11-01', 'nakayama'),
                                          ('V110', '2027-06-01', 'tokyo'), ('J23', '2026-12-01', 'tokyo'),
                                          ('J23', '2026-11-01', 'kyoto')])
def test_outside_scope_is_skip(name, day, course, isolated):
    """範囲外を不正入力や購入見送りと区別する。"""
    result = candidate.predict(envelope(name, day, course), name)
    assert result['status'] == 'skipped' and not result['pairs']


def test_modified_model_is_refused(tmp_path, frozen_models):
    """SHAが違うjoblibはロード前に拒否する。"""
    path = tmp_path / 'bad.joblib'
    path.write_bytes(b'not a model')
    contract = dict(frozen_models[0]['J23'], model=str(path))
    with pytest.raises(ResearchError, match='candidate_model_changed'):
        candidate.load_model('J23', contract)


@pytest.mark.parametrize('name,day', [('J23', '2026-08-30'), ('V110', '2026-09-13')])
def test_training_date_is_not_a_future_test(name, day, isolated):
    """学習末尾と同日の入力を将来予測として使わない。"""
    with pytest.raises(ResearchError, match='candidate_not_after_training'):
        candidate.predict(envelope(name, day), name)


def test_execute_preserves_provenance_and_refuses_overwrite(tmp_path, isolated):
    """新規成果物と元入力SHAを保存し、既存ディレクトリを変更しない。"""
    source = tmp_path / 'input.json'
    source.write_text(json.dumps(envelope()), encoding='utf-8')
    output = tmp_path / 'run'
    candidate.execute(source, output, 'J23')
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['reference_sha256'] == candidate.file_sha(output / 'reference.json')
    assert manifest['status'] == 'complete' and not manifest['performance_eligible']
    with pytest.raises(ResearchError, match='candidate_output_exists'):
        candidate.execute(source, output, 'J23')


def test_partial_write_failure_has_no_complete_manifest(tmp_path, isolated, monkeypatch):
    """途中の書込失敗で正常完了が残らず、失敗理由を保持する。"""
    source = tmp_path / 'input.json'
    source.write_text(json.dumps(envelope()), encoding='utf-8')
    original = candidate.write_json
    def fail_reference(path, value):
        """参照本文の保存失敗だけを再現する。"""
        if path.name == 'reference.json': raise OSError('synthetic_write_failure')
        return original(path, value)
    monkeypatch.setattr(candidate, 'write_json', fail_reference)
    with pytest.raises(ResearchError): candidate.execute(source, tmp_path / 'run', 'J23')
    assert not (tmp_path / 'run/manifest.json').exists()
    assert json.loads((tmp_path / 'run/failure.json').read_text(encoding='utf-8'))['status'] == 'failed'
