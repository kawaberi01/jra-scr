"""概要: S0の全評価確率・精算・保存原本推論を別式で検算する。
作成日: 2026-10-25
入力: 完了したS0 run、元dataset、公式精算、保存原本。
出力: run内のindependent-verification.json。
実行例: uv run --frozen --extra ml python scripts/verify_jra_current_attributes.py
注意事項: 学習・SQL・HTTP・購入なし。一次実装の特徴/推論関数は使わない。
"""

import argparse
from itertools import combinations
import gzip
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_course_chimera as reuse

ROOT = reuse.ROOT


def independent_matrix(r):
    """組合せ列挙と属性の個別演算で14列を再構成する。"""
    attrs = np.asarray(r['attributes'], dtype=np.float32)
    q, pl = np.asarray(r['market']), np.asarray(r['pl'])
    values = []
    for i, (a, b) in enumerate(combinations(range(len(attrs)), 2)):
        means = ((attrs[a]+attrs[b])/np.float32(2)).tolist()
        gaps = np.abs(attrs[a]-attrs[b]).tolist()
        values.append([np.log(q[i]), np.clip(np.log(pl[i]/q[i]), -10, 10), *means, *gaps])
    x = np.asarray(values, dtype=float)
    return (x-np.sum(q[:, None]*x, axis=0)).astype(np.float32)


def independent_predict(fitted, r):
    """条件名を別に構築し、明示的な正規化で全確率を計算する。"""
    assert fitted['trained_through'] < r['race_date']
    c, s = int(r['course']), int(r['surface'])
    d = sum(int(r['distance']) > edge for edge in (1400, 1800, 2200, 2600))
    season = (int(r['race_date'][5:7]) % 12)//3
    names = [f'sd:{s}:{d}', f'cs:{c}:{s}', f'csd:{c}:{s}:{d}', f'season:{season}', f'csds:{c}:{s}:{d}:{season}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    x = independent_matrix(r)/fitted['scale'].astype(np.float32)
    logits = np.log(r['market'])+x @ beta
    p = np.exp(logits-max(logits))
    return p/p.sum()


def verify(folder):
    """保存ファイルと全10,744評価分布を検算し、原本の300推論を照合する。"""
    manifest = reuse.read(folder/'manifest.json')
    for hashes in (manifest['source_sha256'], manifest['frozen_inputs_sha256']):
        assert all(reuse.sha(ROOT/p) == value for p, value in hashes.items())
    assert all(reuse.sha(folder/p) == value for p, value in manifest['files_sha256'].items())
    source = joblib.load(reuse.REFERENCE/'dataset.joblib')
    all_records = source['records']+source['later']
    by_id = {r['race_id']: r for r in all_records}
    outcomes = reuse.read(ROOT/'artifacts/jra_research/d0_usability_20261025_v2/official-outcomes.json')
    checked, settlement_count = 0, 0
    annual = {}
    for year in (2023, 2024, 2025, 2026):
        cell = reuse.read(folder/f'{year}_S0.json')
        fitted = joblib.load(folder/f'{year}_S0.joblib')
        assert cell['train_ids'] == [r['race_id'] for r in source['records'] if r['race_date'] < f'{year}-01-01']
        assert fitted['trained_through'] == max(by_id[key]['race_date'] for key in cell['train_ids'])
        assert cell['test_ids'] == [r['race_id'] for r in all_records if r['race_date'].startswith(str(year))]
        saved = joblib.load(folder/f'{year}_S0_predictions.joblib')
        prefix = '2026_selected' if year == 2026 else f'{year}_D0'
        baseline = joblib.load(reuse.REFERENCE/(prefix+'_predictions.joblib'))
        sums = {k: {'loss': [], 'hits': 0, 'paid': 0} for k in cell['rows']}
        for key, p, b in zip(cell['test_ids'], saved, baseline, strict=True):
            r = by_id[key]
            alt = independent_predict(fitted, r)
            assert np.allclose(alt, p, atol=1e-12, rtol=1e-11)
            assert np.isfinite(p).all() and min(p) > 0 and abs(sum(p)-1) < 1e-9
            for label, prob in [('S0', alt), ('D0', b), ('market', r['market'])]:
                value = sums[label]
                value['loss'].append(float(-np.log(prob[r['winner']])))
                hit = int(np.argmax(prob) == r['winner'])
                payout = r['payout_yen'] if year == 2023 else outcomes[key]['payout_per_100_yen']
                value['hits'] += hit
                value['paid'] += hit*int(payout)
                row = cell['rows'][label][len(value['loss'])-1]
                assert row['race_id'] == key and row['hit'] == hit and row['paid_yen'] == hit*int(payout)
                assert abs(row['loss']-value['loss'][-1]) < 1e-10
                settlement_count += 1
            checked += 1
        annual[str(year)] = {}
        for label, value in sums.items():
            expected = cell['summary'][label]
            assert abs(np.mean(value['loss'])-expected['logloss']) < 1e-10
            assert abs(value['hits']/len(saved)-expected['hit_rate']) < 1e-12
            assert value['paid'] == expected['paid_yen'] and abs(value['paid']/len(saved)-expected['roi_percent']) < 1e-12
            annual[str(year)][label] = {'races': len(saved), 'hits': value['hits'], 'paid_yen': value['paid']}
    replay = reuse.read(folder/'capture-replay.json')
    with gzip.open(ROOT/'artifacts/jra_research/forward_capture_20261025_v4/inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
        observations = [json.loads(line) for line in stream]
    # 原本の変換結果は一次変換器を共有せず、カードと価格から再構成する。
    import re
    fitted = joblib.load(folder/'2026_S0.joblib')
    for item in replay['accepted']:
        obs = observations[item['observation_index']]
        runners = sorted([r for r in obs['card']['runners'] if r.get('status', 'active') == 'active'], key=lambda r: int(r['horse_no']))
        horses = [f"{int(r['horse_no']):02d}" for r in runners]
        attrs = []
        for r in runners:
            sex, age = re.match(r'^(牡|牝|セン|せん|セ|騸)(\d+)', r['sex_age']).groups()
            frame = str(r.get('frame_no') or '').strip()
            attrs.append([int(age)/10, int(sex == '牝'), int(sex in ('セン', 'せん', 'セ', '騸')),
                          int(frame)/8 if frame else .5, int(r['horse_no'])/len(horses), int(not frame)])
        winmap = {int(e['combination'][0]): e['odds'] for e in obs['odds']['win']}
        pairmap = {tuple(sorted(map(int, e['combination']))): e['odds'] for e in obs['odds']['quinella']}
        w = np.asarray([1/winmap[int(h)] for h in horses]); w /= w.sum()
        q = np.asarray([1/pairmap[(int(a), int(b))] for a, b in combinations(horses, 2)]); q /= q.sum()
        pl = np.asarray([w[a]*w[b]*(1/(1-w[a])+1/(1-w[b])) for a, b in combinations(range(len(horses)), 2)]); pl /= pl.sum()
        r = {'race_date': obs['race_date'], 'course': int(obs['race_id'][8:10]),
             'surface': int(obs['card']['surface'] in ('dirt', 'ダート', 1)),
             'distance': int(str(obs['card']['distance']).replace(',', '')), 'market': q, 'pl': pl, 'attributes': attrs}
        p = independent_predict(fitted, r)
        assert horses == item['horses'] and np.allclose(p, item['probabilities'], atol=1e-12, rtol=1e-11)
    assert len(replay['accepted'])+len(replay['rejected']) == len(observations)
    reuse.save(folder/'independent-verification.json', {'status': 'passed', 'evaluation_distributions': checked,
        'settlements': settlement_count, 'capture_distributions': len(replay['accepted']),
        'capture_rejected': len(replay['rejected']), 'annual': annual, 'sources_unchanged': True,
        'verifier_sha256': reuse.sha(Path(__file__)), 'unknown_test': False})
    print(json.dumps({'status': 'passed', 'evaluation_distributions': checked, 'capture_distributions': len(replay['accepted'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT/'artifacts/jra_research/current_attributes_S0_20261025')
    verify(parser.parse_args().run)
