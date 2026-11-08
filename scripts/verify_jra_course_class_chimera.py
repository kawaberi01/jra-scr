"""概要: 場別独立D0と条件コード追加BCの全保存分布・教師期間・選択を別式で検算する。
作成日: 2026-10-25
入力: --run 研究run、--kind course/class、元D0と保存カード。
出力: independent-verification.json。成功0、不一致は非0。
実行例: uv run --frozen --extra ml python scripts/verify_jra_course_class_chimera.py --run artifacts/jra_research/course_D0_20261025_v2 --kind course
注意事項: 学習・SQL・HTTP・予想更新なし。既使用過去の探索を未知試験としない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_quality_chimera as shared
from verify_jra_attribute_chimera import independent_matrix, independent_predict

ROOT, REFERENCE = shared.ROOT, shared.REFERENCE
read, save, sha, helper = shared.read, shared.save, shared.sha, shared.helper


def prediction(fitted, record, kind):
    """本体の行列・推論関数を呼ばず、46列と係数の加算から全分布を再構成する。"""
    if kind == 'course':
        return independent_predict(fitted, record)
    x = independent_matrix(record, 'D0')/fitted['scale'].astype(np.float32)
    c, t, distance = int(record['course']), int(record['surface']), int(record['distance'])
    d = sum(distance > edge for edge in (1400, 1800, 2200, 2600))
    s = (int(record['race_date'][5:7]) % 12)//3
    names = [f'sd:{t}:{d}', f'cs:{c}:{t}', f'csd:{c}:{t}:{d}', f'season:{s}', f'csds:{c}:{t}:{d}:{s}', 'class:'+record['class_code']]
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    z = np.log(record['market'])+x@beta
    p = np.exp(z-max(z))
    return p/p.sum()


def inspect_codes(records, folder):
    """元カードのコード・競走ID・日付・場・距離・芝ダートと欠測を独立に照合する。"""
    manifest = read(folder/'class-input-manifest.json')
    by_id = {r['race_id']: r for r in records}
    seen, coverage = set(), {}
    names = ['sapporo','hakodate','fukushima','niigata','tokyo','nakayama','chukyo','kyoto','hanshin','kokura']
    for relative, digest in manifest['card_sha256'].items():
        path = ROOT/relative
        assert sha(path) == digest
        codes, statuses = Counter(), Counter()
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                source = json.loads(line)
                key = source['race_id']
                if key not in by_id:
                    continue
                r, card = by_id[key], source['race']
                value = str(card.get('condition_code')).strip()
                code = value if re.fullmatch(r'[0-9]{3}', value) and value != '000' else 'UNK'
                assert key not in seen and r['class_code'] == code
                assert r['race_date'] == card['race_date'] and int(r['distance']) == int(card['distance'])
                assert names[int(r['course'])-1] == card['course']
                assert card['surface'] == ('turf' if int(r['surface']) == 0 else 'dirt')
                codes[code] += 1
                statuses[card.get('metadata_asof_status', 'missing')] += 1
                seen.add(key)
        coverage[path.parent.name] = {'codes': dict(codes), 'metadata_asof_status': dict(statuses)}
    assert seen == set(by_id) and coverage == manifest['coverage']
    assert manifest['historical_publication_verified'] is False
    return len(seen)


def metrics_check(record, p, row):
    """確率正規化・ID・日付・場と3指標を直接計算して照合する。"""
    y = record['winner']
    assert row['race_id'] == record['race_id'] and row['race_date'] == record['race_date']
    assert row['course'] == record['course'] and row['surface'] == record['surface']
    assert np.isfinite(p).all() and min(p) > 0 and abs(p.sum()-1) < 1e-9
    assert abs(-np.log(p[y])-row['loss']) < 1e-12
    assert int(np.argmax(p) == y) == row['hit']
    assert abs((p@p-2*p[y]+1)/len(p)-row['brier']) < 1e-14


def verify(folder, kind):
    """全セルの教師と分布、2023選択、後年集計・CIと候補判定を再計算する。"""
    manifest = read(folder/'manifest.json')
    assert not (folder/'failure.json').exists() and manifest['status'] == 'complete'
    assert all(sha(ROOT/p) == value for p, value in manifest['source_sha256'].items())
    assert sha(folder/'assessment.json') == manifest['assessment_sha256']
    inputs = read(folder/'input-manifest.json')
    assert sha(ROOT/inputs['dataset']) == inputs['dataset_sha256']
    assert all(sha(ROOT/p) == v for p, v in inputs['baseline_sha256'].items())
    original = joblib.load(ROOT/inputs['dataset'])
    data = original if kind == 'course' else joblib.load(folder/'dataset.joblib')
    if kind == 'class':
        assert sha(folder/'dataset.joblib') == read(folder/'class-input-manifest.json')['dataset_sha256']
        for old, new in zip(original['records']+original['later'], data['records']+data['later'], strict=True):
            assert set(new) == set(old)|{'class_code'}
            for key in old:
                np.testing.assert_equal(old[key], new[key])
        inspect_codes(data['records']+data['later'], folder)
    records, later = data['records'], data['later']
    baseline, roster = {}, {}
    for year in (2023, 2024, 2025, 2026):
        prefix = '2026_selected' if year == 2026 else f'{year}_D0'
        source = read(REFERENCE/(prefix+'.json'))
        probabilities = joblib.load(REFERENCE/(prefix+'_predictions.joblib'))
        test = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
        assert source['test_ids'] == [r['race_id'] for r in test]
        baseline.update(zip(source['test_ids'], probabilities, strict=True))
        roster[year] = test
    cells, count = {}, 0
    for name, digest in manifest['model_sha256'].items():
        path = folder/name
        assert sha(path) == digest
        cell = read(path.with_suffix('.json'))
        assert cell['model_sha256'] == digest
        year = cell['year']
        course = cell.get('course')
        train = [r for r in records if r['race_date'] < f'{year}-01-01' and (course is None or int(r['course']) == course)]
        test = [r for r in roster[year] if course is None or int(r['course']) == course]
        assert cell['train_ids'] == [r['race_id'] for r in train] and cell['test_ids'] == [r['race_id'] for r in test]
        fitted = joblib.load(path)
        assert fitted['train_races'] == len(train) and fitted['trained_from'] == min(r['race_date'] for r in train)
        assert fitted['trained_through'] == max(r['race_date'] for r in train) < min(r['race_date'] for r in test)
        if course is not None:
            assert fitted['training_scope'] == 'spec395-course-only-D0-v1' and fitted['trained_course'] == course
        else:
            codes = Counter(r['class_code'] for r in train)
            assert dict(codes) == fitted['class_counts'] and not fitted['historical_publication_verified']
            expected = {'class:'+c for c, n in codes.items() if c != 'UNK' and n >= 100}
            assert {n for n in fitted['contexts'] if n.startswith('class:')} == expected
        probabilities = joblib.load(folder/(path.stem+'_predictions.joblib'))
        candidate, common = ('local', 'shared') if kind == 'course' else ('BC', 'D0')
        for i, (r, p) in enumerate(zip(test, probabilities, strict=True)):
            np.testing.assert_allclose(p, prediction(fitted, r, kind), rtol=1e-12, atol=1e-14)
            for key, distribution in ((candidate, p), (common, baseline[r['race_id']]), ('market', r['market'])):
                metrics_check(r, distribution, cell['rows'][key][i])
            count += 1
        assert cell['summary'] == {k: helper.summary(v) for k, v in cell['rows'].items()}
        cells[(year, course)] = cell['rows']
    selection, assessment = read(folder/'selection.json'), read(folder/'assessment.json')
    chosen, totals = {}, {k: [] for k in (candidate, common, 'market', 'selected')}
    courses = range(1, 11) if kind == 'course' else [None]
    for course in courses:
        dev = cells[(2023, course)]
        a, b = helper.summary(dev[candidate]), helper.summary(dev[common])
        use = a['logloss'] < b['logloss']-1e-8 and a['hit_rate'] >= b['hit_rate']
        choice = ('L1' if use else 'L0') if kind == 'course' else ('BC' if use else 'D0')
        chosen[str(course)] = choice
        assert choice == (selection['chosen_by_course'][str(course)] if kind == 'course' else selection['chosen'])
        pooled = {k: [] for k in (candidate, common, 'market', 'selected')}
        annual = {}
        for year in (2024, 2025, 2026):
            rows = dict(cells[(year, course)])
            rows['selected'] = rows[candidate if use else common]
            annual[year] = {k: helper.summary(v) for k, v in rows.items()}
            for key, value in rows.items():
                pooled[key].extend(value)
        a, b = helper.summary(pooled[candidate]), helper.summary(pooled[common])
        ci = helper.comparison_ci(pooled[candidate], pooled[common])
        checks = {('development_selected_local' if kind == 'course' else 'development_selected_BC'): use,
            ('pooled_loss_better_than_shared' if kind == 'course' else 'pooled_loss_better_than_D0'): a['logloss'] < b['logloss'],
            'loss_improvement_ci_positive': ci['loss_improvement_ci95'][0] > 0,
            'market_loss_better_each_year': all(v[candidate]['logloss'] < v['market']['logloss'] for v in annual.values()),
            ('pooled_hits_not_worse_than_shared' if kind == 'course' else 'pooled_hits_not_worse_than_D0'): a['hit_rate'] >= b['hit_rate']}
        saved = assessment['courses'][str(course)] if kind == 'course' else assessment
        assert checks == saved['checks'] and ci == saved['vs_shared_ci' if kind == 'course' else 'vs_D0_ci']
        assert all(checks.values()) == saved['promising_local_research_candidate' if kind == 'course' else 'promising_class_research_candidate']
        assert {k: helper.summary(v) for k, v in pooled.items() if kind == 'course' or k != 'selected'} == saved['pooled']
        for year, value in annual.items():
            expected = assessment['annual'][str(year)][str(course)] if kind == 'course' else assessment['annual'][str(year)]
            assert {k: v for k, v in value.items() if kind == 'course' or k != 'selected'} == expected
        for key, rows in pooled.items():
            totals[key].extend(rows)
    if kind == 'course':
        totals = {k: sorted(v, key=lambda r: r['race_id']) for k, v in totals.items()}
        assert {k: helper.summary(v) for k, v in totals.items()} == assessment['overall']
        assert helper.comparison_ci(totals['selected'], totals['shared']) == assessment['selected_vs_shared_ci']
        final = read(folder/'final-models.json')
        assert sha(folder/'final-models.json') == manifest['final_models_sha256']
        assert final['development_choice_by_course'] == chosen
        assert final['models_by_course'] == {str(c): f'2026_course{c:02d}.joblib' for c in courses}
    output = {'status': 'passed', 'kind': kind, 'cells': len(cells), 'independent_distributions': count,
        'future_training_rows': 0, 'selection_and_gate_verified': True, 'all_metrics_and_CI_verified': True,
        'source_and_model_sha_verified': True, 'unknown_test': False, 'verifier_sha256': sha(Path(__file__))}
    save(folder/'independent-verification.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--kind', choices=('course', 'class'), required=True)
    args = parser.parse_args()
    verify(args.run, args.kind)
