"""概要: S1の過去特徴・保存原本・全予測・固定精算を別式で検算する。
作成日: 2026-10-27
入力: 完了済みS1 run、元年別カード、D0/S0保存予測、公式精算。
出力: run内の独立検算結果。
実行例: uv run --frozen --extra ml python scripts/verify_jra_recent_current.py
注意事項: 学習・SQL・HTTP・既存予想更新なし。一次特徴/推論関数は呼ばない。
"""

import argparse
from collections import Counter
from datetime import date
import gzip
from itertools import combinations, groupby
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_course_chimera as reuse
from verify_jra_current_attributes import independent_matrix as base_matrix

ROOT = reuse.ROOT


def vector(day, surface, distance, previous):
    """前走5値と欠測理由を別の分岐・計算で再構成する。"""
    empty = np.array([0, 0, 0, 0, 1], dtype=np.float32)
    if previous is None:
        return empty, 'unobserved'
    gap = date.fromisoformat(day).toordinal()-date.fromisoformat(previous['race_date']).toordinal()
    assert gap >= 1
    if gap >= 181:
        return empty, 'outside_180d'
    if previous.get('surface') not in [0, 1]:
        return empty, 'unsupported_previous_surface'
    n, rank, dist = [previous.get(k) for k in ['field_size', 'rank', 'distance']]
    if (type(n) is not int or type(rank) is not int or type(dist) is not int or n < 2 or n > 18
            or rank < 1 or rank > n or dist < 800 or dist > 4000 or not previous.get('valid', True)):
        return empty, 'invalid_previous_result'
    return np.array([1-(rank-1)/(n-1), max(-3, min(3, (distance-dist)/400)),
                     int(surface == previous['surface']), gap/180, 0], dtype=np.float32), 'observed'


def independent_matrix(r):
    """24列を組合せ列挙で構築し、一次実装のpair_valuesを使わない。"""
    recent = np.asarray(r['recent'], dtype=np.float32)
    values = []
    for a, b in combinations(range(len(recent)), 2):
        values.append([*((recent[a]+recent[b])/np.float32(2)).tolist(), *np.abs(recent[a]-recent[b]).tolist()])
    x = np.column_stack((base_matrix(r), values)).astype(float)
    return (x-np.sum(np.asarray(r['market'])[:, None]*x, axis=0)).astype(np.float32)


def independent_predict(fitted, r):
    """独立に列挙した条件係数と指数正規化から確率を返す。"""
    assert fitted['trained_through'] < r['race_date']
    c, s = r['course'], r['surface']
    d = sum(r['distance'] > edge for edge in (1400, 1800, 2200, 2600))
    t = (int(r['race_date'][5:7]) % 12)//3
    names = [f'sd:{s}:{d}', f'cs:{c}:{s}', f'csd:{c}:{s}:{d}', f'season:{t}', f'csds:{c}:{s}:{d}:{t}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    x = independent_matrix(r)/np.asarray(fitted['scale'], dtype=np.float32)
    logits = np.log(r['market'])+x @ beta
    weights = np.exp(logits-max(logits))
    return weights/weights.sum()


def verify_features(folder, data):
    """原本を再読し、全特徴が前日以前の同じ馬の直近イベント由来か確認する。"""
    dataset_manifest = reuse.read(folder/'dataset-manifest.json')
    with gzip.open(folder/'feature-provenance.jsonl.gz', 'rt', encoding='utf-8') as stream:
        refs = {row['race_id']: row for row in map(json.loads, stream)}
    by_id = {r['race_id']: r for r in data['records']+data['later']}
    assert set(refs) == set(by_id)
    latest, checked, reasons = {}, 0, Counter()
    for filename, expected_hash in dataset_manifest['card_sha256'].items():
        assert reuse.sha(ROOT/filename) == expected_hash
        with gzip.open(ROOT/filename, 'rt', encoding='utf-8') as stream:
            for day, group in groupby((json.loads(line) for line in stream), key=lambda card: card['race_date']):
                cards = list(group)
                for card in cards:
                    key = card['race_id']
                    if key not in by_id:
                        continue
                    r = by_id[key]
                    runners = {f"{int(row['horse_no']):02d}": row for row in card['inputs']['runners']}
                    assert [ref['horse_no'] for ref in refs[key]['references']] == r['horses']
                    for i, ref in enumerate(refs[key]['references']):
                        row = runners[ref['horse_no']]
                        identity = str(row['horse_id'])
                        previous = latest.get(identity)
                        assert previous == ref['previous'] and identity == ref['horse_id']
                        h = row['history_features']
                        expected_interval = float(h['days_since_last_scaled'])*365
                        assert expected_interval == ref['stored_interval_days'] and float(h['horse_has_history']) == ref['stored_has_history']
                        reason_override = None
                        chosen = previous
                        if previous is not None:
                            days = date.fromisoformat(day).toordinal()-date.fromisoformat(previous['race_date']).toordinal()
                            assert days > 0
                            if float(h['horse_has_history']) != 1 or abs(expected_interval-min(days, 365)) > .0001:
                                chosen, reason_override = None, 'stored_interval_mismatch'
                        expected, reason = vector(day, r['surface'], r['distance'], chosen)
                        reason = reason_override or reason
                        assert np.array_equal(expected, r['recent'][i]) and reason == ref['reason']
                        reasons[reason] += 1
                        checked += 1
                seen = set()
                for card in cards:
                    ranks, statuses = card['result']['ranks_by_horse'], card['result']['runner_statuses']
                    n = len(statuses)
                    valid = 2 <= n <= 18 and sorted(ranks.values()) == list(range(1, n+1)) and {r.get('abnormal_code') for r in statuses.values()} == {'0'}
                    for runner in card['inputs']['runners']:
                        identity = str(runner.get('horse_id') or '')
                        if not identity.isdigit() or len(identity) != 10 or int(identity) == 0:
                            continue
                        assert identity not in seen
                        seen.add(identity)
                        latest[identity] = {'race_id': card['race_id'], 'race_date': day,
                            'surface': {'turf': 0, 'dirt': 1}.get(card['race']['surface']),
                            'distance': card['race']['distance'], 'rank': ranks.get(str(int(runner['horse_no']))),
                            'field_size': n, 'valid': bool(valid)}
    return {'horse_features_checked': checked, 'races': len(by_id), 'coverage': dict(reasons)}


def verify_capture(folder, fitted):
    """原本の最新枠を選び直し、全特徴と保存確率を別式照合する。"""
    replay = reuse.read(folder/'capture-replay.json')
    with gzip.open(ROOT/'artifacts/jra_research/forward_capture_20261025_v4/inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
        observations = [json.loads(line) for line in stream]
    # 市場/属性の再構成はS0独立検算済み原本と同じ順序で行う。
    import re
    coverage = Counter()
    for item in replay['accepted']:
        obs = observations[item['observation_index']]
        runners = sorted([r for r in obs['card']['runners'] if r.get('status', 'active') == 'active'], key=lambda r: int(r['horse_no']))
        horses = [f"{int(r['horse_no']):02d}" for r in runners]
        recent, attrs = [], []
        surface = int(obs['card']['surface'] in ('dirt', 'ダート', 1))
        distance = int(str(obs['card']['distance']).replace(',', ''))
        for i, row in enumerate(runners):
            slots = sorted([s for s in row.get('official_recent_races', []) if s.get('source_date')], key=lambda s: s['source_date'], reverse=True)
            assert all(s['source_date'] < obs['race_date'] for s in slots)
            previous = None
            if slots:
                s = slots[0]
                previous = {'race_date': s['source_date'], 'surface': {'turf': 0, 'dirt': 1, '芝': 0, 'ダート': 1}.get(s.get('surface')),
                    'distance': s.get('distance'), 'rank': s.get('finish_rank'), 'field_size': s.get('field_size'),
                    'valid': s.get('source_course') in ['札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉']}
            v, reason = vector(obs['race_date'], surface, distance, previous)
            assert previous == item['provenance']['previous'][i] and reason == item['provenance']['reasons'][i]
            coverage[reason] += 1
            recent.append(v)
            sex, age = re.match(r'^(牡|牝|セン|せん|セ|騸)(\d+)', row['sex_age']).groups()
            frame = str(row.get('frame_no') or '').strip()
            attrs.append([int(age)/10, int(sex == '牝'), int(sex in ('セン', 'せん', 'セ', '騸')),
                          int(frame)/8 if frame else .5, int(row['horse_no'])/len(runners), int(not frame)])
        win = {int(e['combination'][0]): float(e['odds']) for e in obs['odds']['win']}
        pair = {tuple(sorted(map(int, e['combination']))): float(e['odds']) for e in obs['odds']['quinella']}
        q = np.array([1/pair[(int(a), int(b))] for a, b in combinations(horses, 2)]); q /= sum(q)
        w = np.array([1/win[int(h)] for h in horses]); w /= sum(w)
        pl = np.array([w[a]*w[b]*(1/(1-w[a])+1/(1-w[b])) for a, b in combinations(range(len(horses)), 2)]); pl /= sum(pl)
        r = {'race_date': obs['race_date'], 'course': int(obs['race_id'][8:10]), 'surface': surface,
             'distance': distance, 'attributes': attrs, 'recent': np.asarray(recent, dtype=np.float32), 'market': q, 'pl': pl}
        assert horses == item['horses'] and np.array_equal(r['recent'], np.asarray(item['recent'], dtype=np.float32))
        p = independent_predict(fitted, r)
        assert np.allclose(p, item['probabilities'], atol=1e-12, rtol=1e-11)
    assert len(replay['accepted'])+len(replay['rejected']) == len(observations) and dict(coverage) == replay['recent_coverage']
    return {'distributions': len(replay['accepted']), 'rejected': len(replay['rejected']), 'coverage': dict(coverage)}


def verify(folder):
    """全特徴・評価確率・精算・判定とSHAを検算し、新規証跡を保存する。"""
    manifest = reuse.read(folder/'manifest.json')
    assert manifest['status'] == 'complete'
    for section in ['source_sha256', 'frozen_inputs_sha256']:
        assert all(reuse.sha(ROOT/p) == value for p, value in manifest[section].items())
    assert all(reuse.sha(folder/p) == value for p, value in manifest['files_sha256'].items())
    data = joblib.load(folder/'dataset.joblib')
    feature_check = verify_features(folder, data)
    by_id = {r['race_id']: r for r in data['records']+data['later']}
    outcomes = reuse.read(ROOT/'artifacts/jra_research/d0_usability_20261025_v2/official-outcomes.json')
    annual, pooled = {}, {k: {'races': 0, 'hits': 0, 'paid_yen': 0, 'loss_sum': 0.0} for k in ['S1', 'S0', 'D0', 'market']}
    distributions, settlements = 0, 0
    for year in [2023, 2024, 2025, 2026]:
        cell = reuse.read(folder/f'{year}_S1.json')
        fitted = joblib.load(folder/f'{year}_S1.joblib')
        assert cell['train_ids'] == [r['race_id'] for r in data['records'] if r['race_date'] < f'{year}-01-01']
        assert fitted['trained_through'] == max(by_id[key]['race_date'] for key in cell['train_ids'])
        assert cell['test_ids'] == [r['race_id'] for r in data['records']+data['later'] if r['race_date'].startswith(str(year))]
        p_s1 = joblib.load(folder/f'{year}_S1_predictions.joblib')
        p_s0 = joblib.load(ROOT/f'artifacts/jra_research/current_attributes_S0_20261025/{year}_S0_predictions.joblib')
        prefix = '2026_selected' if year == 2026 else f'{year}_D0'
        p_d0 = joblib.load(reuse.REFERENCE/(prefix+'_predictions.joblib'))
        sums = {k: {'races': 0, 'hits': 0, 'paid_yen': 0, 'loss_sum': 0.0} for k in pooled}
        for index, (key, p, s0, d0) in enumerate(zip(cell['test_ids'], p_s1, p_s0, p_d0, strict=True)):
            r = by_id[key]
            alt = independent_predict(fitted, r)
            assert np.allclose(p, alt, atol=1e-12, rtol=1e-11)
            assert np.isfinite(p).all() and min(p) > 0 and abs(sum(p)-1) < 1e-9
            payout = r['payout_yen'] if year == 2023 else outcomes[key]['payout_per_100_yen']
            if year != 2023:
                pair = list(combinations(r['horses'], 2))[r['winner']]
                assert sorted(map(int, pair)) == sorted(outcomes[key]['winner_pair'])
            for label, prob in [('S1', alt), ('S0', s0), ('D0', d0), ('market', r['market'])]:
                loss, hit = float(-np.log(prob[r['winner']])), int(np.argmax(prob) == r['winner'])
                paid = int(payout)*hit
                row = cell['rows'][label][index]
                assert row['race_id'] == key and row['hit'] == hit and abs(row['loss']-loss) < 1e-10
                assert row['paid_yen'] == paid and row['top_pair_index'] == int(np.argmax(prob))
                sums[label]['races'] += 1
                sums[label]['hits'] += hit
                sums[label]['paid_yen'] += paid
                sums[label]['loss_sum'] += loss
                settlements += 1
            distributions += 1
        annual[str(year)] = sums
        for label, totals in sums.items():
            summary = cell['summary'][label]
            n = totals['races']
            assert abs(totals['loss_sum']/n-summary['logloss']) < 1e-10
            assert abs(totals['hits']/n-summary['hit_rate']) < 1e-12
            assert totals['paid_yen'] == summary['paid_yen'] and abs(totals['paid_yen']/n-summary['roi_percent']) < 1e-12
            if year > 2023:
                for key in totals:
                    pooled[label][key] += totals[key]
    assessment = reuse.read(folder/'assessment.json')
    for label, totals in pooled.items():
        summary = assessment['pooled'][label]
        assert abs(totals['loss_sum']/totals['races']-summary['logloss']) < 1e-10
        assert totals['paid_yen'] == summary['paid_yen'] and summary['stake_yen'] == totals['races']*100
        assert abs(totals['hits']/totals['races']-summary['hit_rate']) < 1e-12
    a, b = annual['2023']['S1'], annual['2023']['S0']
    selected = a['loss_sum']/a['races'] < b['loss_sum']/b['races'] and a['hits'] >= b['hits']
    assert selected == reuse.read(folder/'selection.json')['S1_selected'] == assessment['checks']['development_selected']
    assert assessment['promising_S0_improvement'] == all(assessment['checks'].values())
    assert assessment['promising_D0_replacement'] == (all(assessment['checks'].values()) and all(assessment['D0_checks'].values()))
    capture_check = verify_capture(folder, fitted)
    result = {'status': 'passed', 'features': feature_check, 'evaluation_distributions': distributions,
              'settlements': settlements, 'capture': capture_check, 'sources_unchanged': True,
              'verifier_sha256': reuse.sha(Path(__file__)), 'unknown_test': False, 'refits': 0}
    reuse.save(folder/'independent-verification.json', result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT/'artifacts/jra_research/recent_current_S1_20261027')
    verify(parser.parse_args().run)
