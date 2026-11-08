"""概要: 10競馬場の独立D0を学習し、共有D0と同一競走で固定比較する。
作成日: 2026-10-25
入力: spec395、検算済みD0 datasetと各年の保存分布。
出力: 新規runの40モデル・全分布・教師ID・場別選択/判定とbundle。
実行例: uv run --frozen --extra ml python scripts/run_jra_course_chimera.py --output artifacts/jra_research/course_D0_20261025
注意事項: 旧D0の再学習/SQL/HTTP/予想変更/購入なし。既使用過去の探索。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gc
from pathlib import Path
import shutil

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_quality_chimera as previous
from jra_srb import jra_research_course_chimera as model

ROOT, REFERENCE = previous.ROOT, previous.REFERENCE
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/395-D0競馬場別独立学習の固定比較.md'
read, save, sha, require, log = previous.read, previous.save, previous.sha, previous.require, previous.log
helper = previous.helper
NAMES = {1: '札幌', 2: '函館', 3: '福島', 4: '新潟', 5: '東京', 6: '中山', 7: '中京', 8: '京都', 9: '阪神', 10: '小倉'}


def sources():
    """実行前に固定する元D0と今回の仕様/コードSHAを返す。"""
    return {**read(REFERENCE/'model-manifest.json')['source_sha256'],
        **{str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(model.__file__))}}


def load_inputs(folder):
    """検算済みdatasetと共有D0分布の同一ID/損失を照合して再利用する。"""
    manifest = read(REFERENCE/'model-manifest.json')
    require(sha(REFERENCE/'dataset.joblib') == manifest['dataset_sha256']
        and read(REFERENCE/'independent-verification.json')['status'] == 'passed', 'course_dataset_contract')
    data = joblib.load(REFERENCE/'dataset.joblib')
    records, later = data['records'], data['later']
    all_records = records+later
    by_id = {r['race_id']: r for r in all_records}
    require(len(by_id) == len(all_records) and all(1 <= int(r['course']) <= 10 for r in all_records), 'course_input_identity')
    baselines, hashes = {}, {}
    for year in (2023, 2024, 2025, 2026):
        previous.reference(year)
        prefix = '2026_selected' if year == 2026 else f'{year}_D0'
        cell = read(REFERENCE/(prefix+'.json'))
        probabilities = joblib.load(REFERENCE/(prefix+'_predictions.joblib'))
        expected = [r['race_id'] for r in all_records if r['race_date'].startswith(str(year))]
        require(cell['test_ids'] == expected, 'course_baseline_roster')
        for key, row, p in zip(expected, cell['rows'], probabilities, strict=True):
            r = by_id[key]
            require(abs(-np.log(p[r['winner']])-row['loss']) < 1e-12 and int(np.argmax(p) == r['winner']) == row['hit'], 'course_baseline_value')
            baselines[key] = p
        for filename in (prefix+'.json', prefix+'_predictions.joblib'):
            hashes[str((REFERENCE/filename).relative_to(ROOT))] = sha(REFERENCE/filename)
    save(folder/'input-manifest.json', {'dataset': str((REFERENCE/'dataset.joblib').relative_to(ROOT)),
        'dataset_sha256': manifest['dataset_sha256'], 'baseline_sha256': hashes, 'records': len(records), 'later': len(later)})
    save(folder/'input-acceptance.json', {'status': 'passed', 'course_train_counts_2023':
        {str(c): sum(int(r['course']) == c and r['race_date'] < '2023-01-01' for r in records) for c in NAMES}})
    return records, later, baselines


def metrics(records, probabilities, label):
    """全確率から同じ競走重みの損失・的中・Brierを作る。"""
    rows = []
    for r, p in zip(records, probabilities, strict=True):
        y = r['winner']
        rows.append({k: r[k] for k in ('race_id', 'race_date', 'course', 'surface')}|
            {'distance_band': model.base.core.base.distance_band(r['distance']), 'season': model.base.core.base.season(r['race_date']),
             'label': label, 'loss': float(-np.log(p[y])), 'hit': int(np.argmax(p) == y),
             'brier': float((p@p-2*p[y]+1)/len(p))})
    return rows


def cell(folder, records, test, baselines, year, course, reuse=None):
    """当該場の教師だけで1モデルを作り、全test分布と教師IDを保存する。"""
    train = [r for r in records if r['race_date'] < f'{year}-01-01' and int(r['course']) == course]
    require(bool(train) and bool(test) and all(int(r['course']) == course and r['race_date'].startswith(str(year)) for r in test), 'course_cell_scope')
    prefix = f'{year}_course{course:02d}'
    log('course_fit_start', year=year, course=course, train=len(train), test=len(test))
    path = folder/(prefix+'.joblib')
    reused = reuse is not None and (reuse/(prefix+'.json')).exists()
    if reused:
        prior = read(reuse/(prefix+'.json'))
        require(prior['train_ids'] == [r['race_id'] for r in train] and prior['test_ids'] == [r['race_id'] for r in test]
            and sha(reuse/(prefix+'.joblib')) == prior['model_sha256'], 'course_reused_cell_contract')
        shutil.copy2(reuse/(prefix+'.joblib'), path)
        fitted = joblib.load(path)
    else:
        fitted = model.fit(train, course)
        joblib.dump(fitted, path, compress=3)
    restored = joblib.load(path)
    probabilities = [model.predict(restored, r) for r in test]
    for i in (0, len(test)//2, len(test)-1):
        require(np.array_equal(model.predict(fitted, test[i]), probabilities[i])
            and np.array_equal(model.predict(restored, {**test[i], 'winner': -1, 'payout_yen': -1}), probabilities[i]), 'course_reload_or_result')
    local = metrics(test, probabilities, 'L1')
    shared = metrics(test, [baselines[r['race_id']] for r in test], 'L0')
    market = metrics(test, [r['market'] for r in test], 'M0')
    if reused:
        prior_probabilities = joblib.load(reuse/(prefix+'_predictions.joblib'))
        require(all(np.array_equal(a, b) for a, b in zip(probabilities, prior_probabilities, strict=True))
            and prior['rows'] == {'local': local, 'shared': shared, 'market': market}, 'course_reused_values')
    joblib.dump(probabilities, folder/(prefix+'_predictions.joblib'), compress=3)
    summaries = {k: helper.summary(v) for k, v in [('local', local), ('shared', shared), ('market', market)]}
    save(folder/(prefix+'.json'), {'year': year, 'course': course, 'model_sha256': sha(path),
        'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test],
        'rows': {'local': local, 'shared': shared, 'market': market}, 'summary': summaries, 'reused_completed_fit': reused})
    log('course_fit_complete', year=year, course=course, summary=summaries)
    gc.collect()
    return {'local': local, 'shared': shared, 'market': market}, path


def run(folder, reuse=None):
    """2023の場別選択を固定し、全場独立型と固定ルートの後年成績を保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        require(all(sha(ROOT/p) == value for p, value in initial.items()), 'course_initial_source')
        save(folder/'protocol.json', {'source_sha256': initial, 'courses': NAMES, 'selection_year': 2023,
            'confirmation_years': [2024, 2025, 2026], 'max_new_fits': 40, 'unknown_test': False})
        if reuse is not None:
            prior_sources = read(reuse/'protocol.json')['source_sha256']
            own = str(Path(__file__).relative_to(ROOT))
            require(all(prior_sources[p] == value for p, value in initial.items() if p != own)
                and read(reuse/'failure.json')['type'] == 'FileExistsError', 'course_reuse_source_or_failure')
            save(folder/'reuse-manifest.json', {'source_run': str(reuse), 'prior_source_sha256': prior_sources,
                'reason': 'exclusive progress.json collision; completed models and full predictions revalidated without refit'})
        records, later, baselines = load_inputs(folder)
        if reuse is not None:
            require(read(reuse/'input-manifest.json') == read(folder/'input-manifest.json'), 'course_reuse_input_changed')
        stage = 'development'
        choices, development, model_hashes = {}, {}, {}
        for course in NAMES:
            test = [r for r in records if r['race_date'].startswith('2023') and int(r['course']) == course]
            rows, path = cell(folder, records, test, baselines, 2023, course, reuse)
            a, b = helper.summary(rows['local']), helper.summary(rows['shared'])
            choices[str(course)] = 'L1' if a['logloss'] < b['logloss']-1e-8 and a['hit_rate'] >= b['hit_rate'] else 'L0'
            development[str(course)] = {k: helper.summary(v) for k, v in rows.items()}
            model_hashes[path.name] = sha(path)
        save(folder/'selection.json', {'chosen_by_course': choices, 'development': development, 'confirmation_used': False})
        stage = 'confirmation'
        annual, pooled, final_paths = {}, {str(c): {k: [] for k in ('local', 'shared', 'market', 'selected')} for c in NAMES}, {}
        for year in (2024, 2025, 2026):
            annual[str(year)] = {}
            test_year = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
            for course in NAMES:
                test = [r for r in test_year if int(r['course']) == course]
                rows, path = cell(folder, records, test, baselines, year, course, reuse)
                model_hashes[path.name] = sha(path)
                rows['selected'] = rows['local'] if choices[str(course)] == 'L1' else rows['shared']
                annual[str(year)][str(course)] = {k: helper.summary(v) for k, v in rows.items()}
                for k, v in rows.items():
                    pooled[str(course)][k].extend(v)
                if year == 2026:
                    final_paths[str(course)] = path.name
        stage = 'assessment'
        assessments = {}
        for course in NAMES:
            values = pooled[str(course)]
            a, b = helper.summary(values['local']), helper.summary(values['shared'])
            ci = helper.comparison_ci(values['local'], values['shared'])
            checks = {'development_selected_local': choices[str(course)] == 'L1',
                'pooled_loss_better_than_shared': a['logloss'] < b['logloss'],
                'loss_improvement_ci_positive': ci['loss_improvement_ci95'][0] > 0,
                'market_loss_better_each_year': all(annual[str(y)][str(course)]['local']['logloss'] < annual[str(y)][str(course)]['market']['logloss'] for y in (2024, 2025, 2026)),
                'pooled_hits_not_worse_than_shared': a['hit_rate'] >= b['hit_rate']}
            assessments[str(course)] = {'name': NAMES[course], 'chosen_in_development': choices[str(course)],
                'pooled': {k: helper.summary(v) for k, v in values.items()}, 'vs_shared_ci': ci,
                'checks': checks, 'promising_local_research_candidate': all(checks.values())}
        totals = {k: sorted([r for values in pooled.values() for r in values[k]], key=lambda r: r['race_id']) for k in ('local', 'shared', 'market', 'selected')}
        save(folder/'assessment.json', {'courses': assessments, 'annual': annual,
            'overall': {k: helper.summary(v) for k, v in totals.items()},
            'selected_vs_shared_ci': helper.comparison_ci(totals['selected'], totals['shared']),
            'promising_local_courses': [int(c) for c, v in assessments.items() if v['promising_local_research_candidate']],
            'unknown_test': False, 'production_adoption': False, 'default_model_changed': False})
        save(folder/'final-models.json', {'models_by_course': final_paths, 'development_choice_by_course': choices,
            'scope': model.SCOPE, 'global_reference': str(REFERENCE.relative_to(ROOT)), 'research_only': True})
        require(sources() == initial and all(sha(ROOT/p) == v for p, v in initial.items()), 'course_final_source_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial, 'model_sha256': model_hashes,
            'new_fits': len(model_hashes), 'D0_refits': 0, 'assessment_sha256': sha(folder/'assessment.json'),
            'final_models_sha256': sha(folder/'final-models.json')})
        log('course_research_complete', new_fits=len(model_hashes), choices=choices,
            promising_local_courses=[c for c, a in assessments.items() if a['promising_local_research_candidate']])
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse-initial-cells', type=Path)
    with threadpool_limits(limits=1):
        args = parser.parse_args()
        run(args.output, args.reuse_initial_cells)
