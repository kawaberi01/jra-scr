"""概要: D0と固定3gateを2023年で選抜し、翌3年を固定比較する。
作成日: 2026-10-24
入力: spec370、検算済みD0モデルと属性付きdataset。
出力: 新規runの全予測・教師ID・選抜・更新条件・SHA証跡。
実行例: uv run --frozen --extra ml python scripts/run_jra_quality_chimera.py --output artifacts/jra_research/quality_chimera_20261024
注意事項: SQL/HTTP/実購入なし。過去の探索、未知評価ではない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gc
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_attribute_chimera as previous
from jra_srb import jra_research_quality_chimera as model

ROOT = previous.ROOT
REFERENCE = ROOT/'artifacts/jra_research/market_attribute_chimera_20261024_v3'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/370-履歴信頼度と条件変更の相互作用.md'
ORDER = ('D0', *model.CASES)
read, save, sha, require, log = previous.read, previous.save, previous.sha, previous.require, previous.log
helper = previous.previous.old.prior


def sources():
    """今回の仕様・計算コードと、既存D0の固定コードSHAを列挙する。"""
    paths = (SPEC, Path(__file__), Path(model.__file__))
    return {**read(REFERENCE/'model-manifest.json')['source_sha256'],
            **{str(p.relative_to(ROOT)): sha(p) for p in paths}}


def reference(year):
    """完成済みD0の各年モデルをSHA検査付きで再利用する。"""
    path = REFERENCE/('final_model.joblib' if year == 2026 else f'{year}_D0.joblib')
    manifest = read(REFERENCE/('model-manifest.json' if year == 2026 else f'{year}_D0.json'))
    require(sha(path) == manifest['model_sha256'], 'quality_reference_sha')
    return joblib.load(path)


def measure(records, fitted, label):
    """全分布と、等競走重みの損失・1位的中を計測する。"""
    rows, probabilities = [], []
    for r in records:
        p = np.asarray(r['market']) if fitted is None else model.predict(fitted, r)
        y = r['winner']
        rows.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'label': label,
            'course': r['course'], 'surface': r['surface'], 'distance_band': model.base.core.base.distance_band(r['distance']),
            'season': model.base.core.base.season(r['race_date']), 'loss': float(-np.log(p[y])),
            'hit': int(np.argmax(p) == y), 'brier': float((p@p-2*p[y]+1)/len(p))})
        probabilities.append(p)
    return rows, probabilities


def cell(folder, train, test, year, case):
    """新案だけを学習し、再読込・結果遮断を検査して全分布を保存する。"""
    log('quality_fit', year=year, case=case, train_races=len(train), reused=case == 'D0')
    fitted = reference(year) if case == 'D0' else model.fit(train, case)
    path = folder/f'{year}_{case}.joblib'
    joblib.dump(fitted, path, compress=3)
    restored = joblib.load(path)
    rows, probabilities = measure(test, restored, case)
    for i in (0, len(test)//2, len(test)-1):
        require(np.array_equal(model.predict(fitted, test[i]), probabilities[i]), 'quality_reload_changed')
        require(np.array_equal(model.predict(restored, {**test[i], 'winner': -1, 'payout_yen': -1}), probabilities[i]), 'quality_result_dependency')
    joblib.dump(probabilities, folder/f'{year}_{case}_predictions.joblib', compress=3)
    save(folder/f'{year}_{case}.json', {'case': case, 'year': year, 'rows': rows, 'summary': helper.summary(rows),
        'model_sha256': sha(path), 'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test]})
    log('quality_evaluated', year=year, case=case, **helper.summary(rows))
    gc.collect()
    return rows


def run(folder):
    """事前固定の選抜と更新判定を行い、失敗時は証跡を残して停止する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        require(all(sha(ROOT/p) == value for p, value in initial.items()), 'quality_source_changed')
        prior_manifest = read(REFERENCE/'model-manifest.json')
        dataset = REFERENCE/'dataset.joblib'
        require(sha(dataset) == prior_manifest['dataset_sha256'] and read(REFERENCE/'independent-verification.json')['status'] == 'passed', 'quality_input_sha')
        data = joblib.load(dataset)
        records, later = data['records'], data['later']
        save(folder/'protocol.json', {'source_sha256': initial, 'cases': list(ORDER), 'selection_year': 2023,
            'confirmation_years': [2024, 2025, 2026], 'max_new_fits': 6, 'unknown_test': False})
        save(folder/'input-manifest.json', {'dataset': str(dataset.relative_to(ROOT)), 'dataset_sha256': sha(dataset),
            'reference_manifest_sha256': sha(REFERENCE/'model-manifest.json'), 'records': len(records), 'later': len(later)})
        for record in records+later:
            for case in model.CASES:
                model.matrix(model.clean(record), case)
        save(folder/'input-acceptance.json', {'status': 'passed', 'races': len(records)+len(later), 'all_three_matrices': True})
        stage = 'development'
        train = [r for r in records if r['race_date'] < '2023-01-01']
        test = [r for r in records if r['race_date'].startswith('2023')]
        development = {case: helper.summary(cell(folder, train, test, 2023, case)) for case in ORDER}
        minimum = min(v['logloss'] for v in development.values())
        chosen = next(c for c in ORDER if development[c]['logloss'] <= minimum+1e-8)
        save(folder/'selection.json', {'chosen': chosen, 'criterion': '2023_logloss_only_tie_simple',
            'development': development, 'confirmation_used': False})
        log('quality_selection_frozen', chosen=chosen)
        stage = 'confirmation'
        annual, candidate, baseline, market = {}, [], [], []
        for year in (2024, 2025):
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = [r for r in records if r['race_date'].startswith(str(year))]
            b = cell(folder, train, test, year, 'D0')
            a = b if chosen == 'D0' else cell(folder, train, test, year, chosen)
            m, _ = measure(test, None, 'M0')
            annual[str(year)] = {k: helper.grouped(v) for k, v in [('selected', a), ('D0', b), ('market', m)]}
            candidate.extend(a)
            baseline.extend(b)
            market.extend(m)
        stage = 'final_fit'
        final = reference(2026) if chosen == 'D0' else model.fit(records, chosen)
        joblib.dump(final, folder/'final_model.joblib', compress=3)
        restored = joblib.load(folder/'final_model.joblib')
        require(np.array_equal(model.predict(final, later[0]), model.predict(restored, later[0])), 'quality_final_reload')
        a, distributions = measure(later, restored, chosen)
        b, _ = measure(later, reference(2026), 'D0')
        m, _ = measure(later, None, 'M0')
        joblib.dump(distributions, folder/'2026_selected_predictions.joblib', compress=3)
        save(folder/'2026_selected.json', {'rows': a, 'test_ids': [r['race_id'] for r in later]})
        annual['2026'] = {k: helper.grouped(v) for k, v in [('selected', a), ('D0', b), ('market', m)]}
        candidate.extend(a)
        baseline.extend(b)
        market.extend(m)
        ci = helper.comparison_ci(candidate, baseline)
        a, b = helper.summary(candidate), helper.summary(baseline)
        checks = {'pooled_loss_better_than_D0': a['logloss'] < b['logloss'],
            'pooled_D0_loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
            'market_loss_better_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in annual.values()),
            'pooled_hit_rate_not_worse_than_D0': a['hit_rate'] >= b['hit_rate']}
        save(folder/'assessment.json', {'selected': chosen, 'confirmation': annual, 'pooled_selected': a, 'pooled_D0': b,
            'vs_D0_ci': ci, 'vs_market_ci': helper.comparison_ci(candidate, market), 'additional_promising_checks': checks,
            'replace_D0_as_research_candidate': all(checks.values()), 'top1_superiority_evidence': ci['hit_rate_difference_ci95'][0] > 0,
            'unknown_test': False, 'production_adoption': False})
        require(sources() == initial and all(sha(ROOT/p) == v for p, v in initial.items()), 'quality_final_source_changed')
        save(folder/'model-manifest.json', {'selected': chosen, 'model_sha256': sha(folder/'final_model.joblib'),
            'source_sha256': initial, 'dataset_sha256': sha(dataset), 'assessment_sha256': sha(folder/'assessment.json'),
            'train_ids': [r['race_id'] for r in records], 'trained_through': final['trained_through']})
        save(folder/'verification.json', {'status': 'passed', 'result_ignored': True, 'reload_equal': True, 'sources_unchanged': True})
        log('quality_complete', selected=chosen, checks=checks, pooled=a, D0=b)
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
