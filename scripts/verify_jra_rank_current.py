"""概要: S2の全スコア・純順位目的・固定精算・区間・採否を独立検算する。
作成日: 2026-11-05
入力: 完了S2 run、元dataset、S0/D0保存分布、公式精算、保存原本。
出力: run内のindependent-verification.json。
実行例: uv run --frozen --extra ml python scripts/verify_jra_rank_current.py
注意事項: 一次特徴/推論/目的関数を呼ばず、再学習・SQL・外部取得なし。
"""

import argparse
from collections import defaultdict
import gzip
from itertools import combinations
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_course_chimera as reuse

ROOT = reuse.ROOT
S0 = ROOT/'artifacts/jra_research/current_attributes_S0_20261025'


def features(record):
    """14列を別のペア列挙で作り、中心化の内積/float32境界を守る。"""
    attrs = np.asarray(record['attributes'], dtype=np.float32)
    q, pl = np.asarray(record['market'], dtype=float), np.asarray(record['pl'], dtype=float)
    values = []
    for i, (a, b) in enumerate(combinations(range(len(attrs)), 2)):
        values.append([np.log(q[i]), max(-10, min(10, np.log(pl[i]/q[i]))),
                       *((attrs[a]+attrs[b])/np.float32(2)).tolist(), *np.abs(attrs[a]-attrs[b]).tolist()])
    x = np.asarray(values, dtype=float)
    x -= np.dot(q, x)
    return x.astype(np.float32)


def scores(fitted, record, enforce_date=True):
    """条件名を独立に構築して線形スコアを返す。教師目的再計算時だけ日付検査を外す。"""
    if enforce_date:
        assert fitted['trained_through'] < record['race_date']
    course, surface = int(record['course']), int(record['surface'])
    band = sum(record['distance'] > edge for edge in (1400, 1800, 2200, 2600))
    season = (int(record['race_date'][5:7]) % 12)//3
    names = [f'sd:{surface}:{band}', f'cs:{course}:{surface}', f'csd:{course}:{surface}:{band}',
             f'season:{season}', f'csds:{course}:{surface}:{band}:{season}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    x = features(record)/fitted['scale'].astype(np.float32)
    return np.log(record['market'])+x @ beta


def summary(rows):
    """確率指標を作らず、整数精算と順位を独立に集計する。"""
    count = len(rows)
    hits, paid = sum(r['hit'] for r in rows), sum(r['paid_yen'] for r in rows)
    return {'races': count, 'days': len(set(r['race_date'] for r in rows)), 'hits': hits,
            'hit_rate': hits/count, 'stake_yen': count*100, 'paid_yen': paid,
            'net_yen': paid-count*100, 'roi_percent': paid/count,
            'mean_winner_rank': sum(r['winner_rank'] for r in rows)/count}


def intervals(a, b):
    """開催日の抽出回数を数えて、的中率差と回収差の区間を別式で求める。"""
    days = sorted(set(r['race_date'] for r in a))
    lookup = {day: i for i, day in enumerate(days)}
    values = np.zeros((len(days), 3), dtype=np.int64)
    assert [r['race_id'] for r in a] == [r['race_id'] for r in b]
    for x, y in zip(a, b, strict=True):
        assert x['race_date'] == y['race_date']
        i = lookup[x['race_date']]
        values[i] += [1, x['hit']-y['hit'], x['paid_yen']-y['paid_yen']]
    samples = np.random.default_rng(435).integers(0, len(days), size=(2000, len(days)))
    estimates = []
    for sample in samples:
        multiplicities = np.bincount(sample, minlength=len(days))
        totals = multiplicities @ values
        estimates.append([totals[1]/totals[0], totals[2]/totals[0]])
    bounds = np.quantile(estimates, [.025, .975], axis=0)
    return {'days': len(days), 'draws': 2000, 'seed': 435,
            'hit_rate_difference_ci95': bounds[:, 0].tolist(), 'roi_difference_pp_ci95': bounds[:, 1].tolist()}


def capture_record(obs):
    """原本の馬番・属性・単勝/馬連からS0と同じ許可入力だけを再構成する。"""
    runners = sorted([r for r in obs['card']['runners'] if r.get('status', 'active') == 'active'], key=lambda r: int(r['horse_no']))
    horses, attrs = [f"{int(r['horse_no']):02d}" for r in runners], []
    for row in runners:
        sex, age = re.match(r'^(牡|牝|セン|せん|セ|騸)(\d+)', row['sex_age']).groups()
        frame = str(row.get('frame_no') or '').strip()
        attrs.append([int(age)/10, int(sex == '牝'), int(sex in ['セン', 'せん', 'セ', '騸']),
                      int(frame)/8 if frame else .5, int(row['horse_no'])/len(runners), int(not frame)])
    win = {int(e['combination'][0]): float(e['odds']) for e in obs['odds']['win']}
    pair = {tuple(sorted(map(int, e['combination']))): float(e['odds']) for e in obs['odds']['quinella']}
    q = np.asarray([1/pair[(int(a), int(b))] for a, b in combinations(horses, 2)]); q /= q.sum()
    w = np.asarray([1/win[int(h)] for h in horses]); w /= w.sum()
    pl = np.asarray([w[a]*w[b]*(1/(1-w[a])+1/(1-w[b])) for a, b in combinations(range(len(horses)), 2)]); pl /= pl.sum()
    return {'race_id': obs['race_id'], 'race_date': obs['race_date'], 'course': int(obs['race_id'][8:10]),
            'surface': int(obs['card']['surface'] in ('dirt', 'ダート', 1)),
            'distance': int(str(obs['card']['distance']).replace(',', '')), 'horses': horses,
            'attributes': attrs, 'market': q, 'pl': pl}


def training_objective(fitted, records):
    """教師の実スコア差だけから純順位目的と比較数を独立再計算する。"""
    losses, comparisons = [], 0
    for r in records:
        values = scores(fitted, r, enforce_date=False)
        order = sorted(range(len(r['market'])), key=lambda i: (-r['market'][i], i))[:5]
        negatives = [i for i in order if i != r['winner']]
        assert len(negatives) in (4, 5)
        comparisons += len(negatives)
        losses.append(float(np.mean(np.logaddexp(0, values[negatives]-values[r['winner']]))))
    beta = fitted['coef']
    penalty = (.1*np.square(beta[0]).sum()+np.square(beta[1:]).sum())/2
    return float(np.mean(losses)+penalty), comparisons


def verify(folder):
    """ソース/尺度/訓練目的・全順位・精算・区間・採否・原本互換を検算する。"""
    manifest = reuse.read(folder/'manifest.json')
    assert manifest['status'] == 'complete' and manifest['new_fits'] == 4
    for field in ['source_sha256', 'frozen_inputs_sha256']:
        assert all(reuse.sha(ROOT/p) == value for p, value in manifest[field].items())
    assert all(reuse.sha(folder/p) == value for p, value in manifest['files_sha256'].items())
    data = joblib.load(reuse.REFERENCE/'dataset.joblib')
    all_records = data['records']+data['later']
    by_id = {r['race_id']: r for r in all_records}
    outcomes = reuse.read(ROOT/'artifacts/jra_research/d0_usability_20261025_v2/official-outcomes.json')
    annual, pooled, objectives = {}, {k: [] for k in ['S2', 'S0', 'D0', 'market']}, {}
    checked, settlements = 0, 0
    for year in [2023, 2024, 2025, 2026]:
        cell = reuse.read(folder/f'{year}_S2.json')
        fitted = joblib.load(folder/f'{year}_S2.joblib')
        s0_model = joblib.load(S0/f'{year}_S0.joblib')
        assert np.array_equal(fitted['scale'], s0_model['scale']) and fitted['contexts'] == s0_model['contexts']
        assert fitted['context_counts'] == s0_model['context_counts'] and fitted['output_kind'] == 'rank_score_not_probability'
        train = [r for r in data['records'] if r['race_date'] < f'{year}-01-01']
        assert cell['train_ids'] == [r['race_id'] for r in train]
        assert fitted['trained_through'] == max(r['race_date'] for r in train)
        assert cell['test_ids'] == [r['race_id'] for r in all_records if r['race_date'].startswith(str(year))]
        objective, comparisons = training_objective(fitted, train)
        assert abs(objective-fitted['optimizer']['loss']) < 1e-8 and comparisons == fitted['train_comparisons']
        objectives[str(year)] = {'objective': objective, 'comparisons': comparisons, 'S0_scale_context_equal': True}
        arrays = joblib.load(folder/f'{year}_S2_scores.joblib')
        baseline = {'S0': joblib.load(S0/f'{year}_S0_predictions.joblib'),
                    'D0': joblib.load(reuse.REFERENCE/(('2026_selected' if year == 2026 else f'{year}_D0')+'_predictions.joblib'))}
        for i, (key, saved) in enumerate(zip(cell['test_ids'], arrays, strict=True)):
            r = by_id[key]
            alt = scores(fitted, r)
            assert np.isfinite(saved).all() and np.allclose(alt, saved, atol=1e-12, rtol=1e-11)
            payout = r['payout_yen'] if year == 2023 else outcomes[key]['payout_per_100_yen']
            if year > 2023:
                assert sorted(map(int, list(combinations(r['horses'], 2))[r['winner']])) == sorted(outcomes[key]['winner_pair'])
            for label, value in [('S2', alt), ('S0', baseline['S0'][i]), ('D0', baseline['D0'][i]), ('market', r['market'])]:
                order = sorted(range(len(value)), key=lambda j: (-float(value[j]), j))
                top, hit = order[0], int(order[0] == r['winner'])
                row = cell['rows'][label][i]
                assert row['race_id'] == key and row['top_pair_index'] == top and row['winner_rank'] == order.index(r['winner'])+1
                assert row['hit'] == hit and row['paid_yen'] == int(payout)*hit
                assert not any(k in row for k in ('loss', 'brier', 'probability'))
                if year > 2023:
                    pooled[label].append(row)
                settlements += 1
            checked += 1
        annual[str(year)] = {k: summary(v) for k, v in cell['rows'].items()}
        assert annual[str(year)] == cell['summary']
    assessment = reuse.read(folder/'assessment.json')
    assert {k: summary(v) for k, v in pooled.items()} == assessment['pooled'] and annual == assessment['annual']
    for label in ['S0', 'D0', 'market']:
        assert intervals(pooled['S2'], pooled[label]) == assessment['intervals'][label]
    selected = annual['2023']['S2']['hits'] > annual['2023']['S0']['hits'] and annual['2023']['S2']['roi_percent'] >= annual['2023']['S0']['roi_percent']
    assert selected == reuse.read(folder/'selection.json')['S2_selected']
    checks = {'development_selected': selected,
        'S0_hit_difference_ci_positive': assessment['intervals']['S0']['hit_rate_difference_ci95'][0] > 0,
        'roi_at_least_S0': summary(pooled['S2'])['roi_percent'] >= summary(pooled['S0'])['roi_percent'],
        'annual_hit_drop_within_half_pp': all(annual[str(y)]['S2']['hit_rate'] >= annual[str(y)]['S0']['hit_rate']-.005 for y in [2024, 2025, 2026])}
    d0_checks = {'D0_hit_difference_ci_positive': assessment['intervals']['D0']['hit_rate_difference_ci95'][0] > 0,
                 'roi_at_least_D0': summary(pooled['S2'])['roi_percent'] >= summary(pooled['D0'])['roi_percent']}
    assert checks == assessment['checks'] and d0_checks == assessment['D0_checks']
    assert all(checks.values()) == assessment['promising_S0_improvement']
    assert (all(checks.values()) and all(d0_checks.values())) == assessment['promising_D0_replacement']
    for label, rows in pooled.items():
        for field in ['course', 'surface', 'distance_band', 'season']:
            for key, saved_summary in assessment['grouped'][label][field].items():
                assert summary([r for r in rows if str(r[field]) == key]) == saved_summary
    replay = reuse.read(folder/'capture-replay.json')
    with gzip.open(ROOT/'artifacts/jra_research/forward_capture_20261025_v4/inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
        observations = [json.loads(line) for line in stream]
    for item in replay['accepted']:
        r = capture_record(observations[item['observation_index']])
        values = scores(fitted, r)
        assert r['race_id'] == item['race_id'] and r['horses'] == item['horses']
        assert np.allclose(values, item['scores'], atol=1e-12, rtol=1e-11)
        assert sorted(range(len(values)), key=lambda i: (-float(values[i]), i)) == item['pair_order']
        assert 'probabilities' not in item
    assert len(replay['accepted'])+len(replay['rejected']) == len(observations)
    result = {'status': 'passed', 'evaluation_score_vectors': checked, 'settlements': settlements,
        'training_objectives': objectives, 'all_bootstrap_and_decisions_reproduced': True,
        'capture_score_vectors': len(replay['accepted']), 'capture_rejected': len(replay['rejected']),
        'scores_not_probabilities': True, 'sources_unchanged': True, 'refits': 0, 'unknown_test': False,
        'verifier_sha256': reuse.sha(Path(__file__))}
    reuse.save(folder/'independent-verification.json', result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT/'artifacts/jra_research/rank_current_S2_20261105')
    verify(parser.parse_args().run)
