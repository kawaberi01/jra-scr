"""概要: D0の確率偏りを診断し、校正期間と選択期間を分けた固定4案を比較する。
作成日: 2026-10-25
入力: spec380、検算済みD0のdatasetと2023〜2026保存分布。
出力: 新規runの診断/校正係数/全予測/選抜/確認/入力SHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_d0_calibration.py --output artifacts/jra_research/d0_calibration_20261025
注意事項: D0再学習/SQL/HTTP/購入なし。既使用過去の探索的検証。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np

import run_jra_quality_chimera as previous
from jra_srb import jra_research_d0_calibration as model

ROOT, REFERENCE = previous.ROOT, previous.REFERENCE
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/380-D0確率偏り診断と固定校正.md'
read, save, sha, require = previous.read, previous.save, previous.sha, previous.require
helper = previous.helper


def sources():
    """新仕様・校正コードと既存D0の固定ソースSHAをまとめる。"""
    return {**read(REFERENCE/'model-manifest.json')['source_sha256'],
        **{str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(model.__file__))}}


def prepare(folder):
    """保存D0確率のID/正解損失を照合し、校正に必要な最小入力だけを保存する。"""
    manifest = read(REFERENCE/'model-manifest.json')
    require(sha(REFERENCE/'dataset.joblib') == manifest['dataset_sha256']
        and read(REFERENCE/'independent-verification.json')['status'] == 'passed', 'D0_calibration_source')
    data = joblib.load(REFERENCE/'dataset.joblib')
    raw = data['records']+data['later']
    by_id = {r['race_id']: r for r in raw}
    records, inputs = [], {}
    for year in (2023, 2024, 2025, 2026):
        name = '2026_selected' if year == 2026 else f'{year}_D0'
        cell = read(REFERENCE/(name+'.json'))
        probabilities = joblib.load(REFERENCE/(name+'_predictions.joblib'))
        previous.reference(year)
        expected = [r['race_id'] for r in raw if r['race_date'].startswith(str(year))]
        require(cell['test_ids'] == expected, 'D0_calibration_source_ids')
        for key, row, p in zip(cell['test_ids'], cell['rows'], probabilities, strict=True):
            original = by_id[key]
            record = {k: original[k] for k in ('race_id', 'race_date', 'course', 'surface', 'distance', 'winner')}
            record.update(p=np.asarray(p, dtype=float), q=np.asarray(original['market'], dtype=float),
                distance_band=row['distance_band'], season=row['season'])
            model.validate(record)
            require(abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
                and int(np.argmax(p) == record['winner']) == row['hit'], 'D0_calibration_source_values')
            records.append(record)
        for filename in (name+'.json', name+'_predictions.joblib'):
            path = REFERENCE/filename
            inputs[str(path.relative_to(ROOT))] = sha(path)
    joblib.dump(records, folder/'inputs.joblib', compress=3)
    save(folder/'input-manifest.json', {'input_sha256': sha(folder/'inputs.joblib'),
        'D0_dataset_sha256': manifest['dataset_sha256'], 'source_prediction_sha256': inputs, 'records': len(records)})
    return records


def diagnose(records):
    """固定条件の正解確率・損失差・1位確信度を記述し、因果を断定しない。"""
    def summarize(rows):
        """対応競走の平均損失と的中数を集計する。"""
        if not rows:
            return {'races': 0}
        differences = [float(np.log(r['q'][r['winner']]/r['p'][r['winner']])) for r in rows]
        return {'races': len(rows), 'D0_loss': float(np.mean([-np.log(r['p'][r['winner']]) for r in rows])),
            'market_loss': float(np.mean([-np.log(r['q'][r['winner']]) for r in rows])),
            'D0_hits': sum(int(np.argmax(r['p']) == r['winner']) for r in rows),
            'market_hits': sum(int(np.argmax(r['q']) == r['winner']) for r in rows),
            'D0_minus_market_loss_sum': float(sum(differences)),
            'mean_D0_max_probability': float(np.mean([max(r['p']) for r in rows]))}
    output = {}
    for name, subset in [('all', records), ('nakayama_turf_1801_2200', [r for r in records if r['course'] == 6 and r['surface'] == 0 and r['distance_band'] == 2])]:
        groups = {}
        for year in (2023, 2024, 2025, 2026):
            rows = [r for r in subset if r['race_date'].startswith(str(year))]
            groups[str(year)] = summarize(rows)
        confirmation = [r for r in subset if r['race_date'] >= '2024-01-01']
        top = sorted(confirmation, key=lambda r: np.log(r['q'][r['winner']]/r['p'][r['winner']]), reverse=True)[:10]
        bins = []
        for lo, hi in zip((0, .05, .1, .2, .4), (.05, .1, .2, .4, 1.0000001), strict=True):
            bins.append({'min': lo, 'max': hi, **summarize([r for r in confirmation if lo <= max(r['p']) < hi])})
        output[name] = {'years': groups, 'confirmation': summarize(confirmation), 'top_probability_bins': bins,
            'D0_hit': summarize([r for r in confirmation if np.argmax(r['p']) == r['winner']]),
            'D0_miss': summarize([r for r in confirmation if np.argmax(r['p']) != r['winner']]),
            'top1_agreement': summarize([r for r in confirmation if np.argmax(r['p']) == np.argmax(r['q'])]),
            'top1_disagreement': summarize([r for r in confirmation if np.argmax(r['p']) != np.argmax(r['q'])]),
            'true_D0_probability_under_001': summarize([r for r in confirmation if r['p'][r['winner']] < .01]),
            'ten_largest_loss_increases': [{'race_id': r['race_id'], 'D0_probability': float(r['p'][r['winner']]),
                'market_probability': float(r['q'][r['winner']]), 'loss_difference': float(np.log(r['q'][r['winner']]/r['p'][r['winner']]))} for r in top],
            'after_removing_ten_largest': summarize([r for r in confirmation if r['race_id'] not in {v['race_id'] for v in top}])}
    return output


def measure(records, fitted):
    """校正期間外の全確率を保存用の競走別指標へ変換する。"""
    rows, probabilities = [], []
    for r in records:
        p = model.predict(fitted, r)
        y = r['winner']
        rows.append({k: r[k] for k in ('race_id', 'race_date', 'course', 'surface', 'distance_band', 'season')}|
            {'label': fitted['case'], 'loss': float(-np.log(p[y])), 'hit': int(np.argmax(p) == y),
             'brier': float((p@p-2*p[y]+1)/len(p))})
        probabilities.append(p)
    return rows, probabilities


def run(folder):
    """校正→別期間選択→翌年固定確認を行い、入力とソースの不変性を確認する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        require(all(sha(ROOT/p) == value for p, value in initial.items()), 'D0_calibration_initial_sources')
        save(folder/'protocol.json', {'source_sha256': initial, 'cases': list(model.CASES),
            'calibration': ['2023-01-01', '2023-08-31'], 'selection': ['2023-09-01', '2023-12-31'],
            'confirmation_years': [2024, 2025, 2026], 'unknown_test': False, 'D0_refits': 0})
        records = prepare(folder)
        save(folder/'diagnostic.json', diagnose(records))
        fit_rows = [r for r in records if model.FIT_FROM <= r['race_date'] <= model.FIT_THROUGH]
        selection_rows = [r for r in records if '2023-09-01' <= r['race_date'] <= '2023-12-31']
        require(set(r['race_id'] for r in fit_rows).isdisjoint(r['race_id'] for r in selection_rows), 'D0_calibration_overlap')
        stage = 'calibration_and_selection'
        models, scores = {}, {}
        for case in model.CASES:
            fitted = model.fit(fit_rows, case)
            save(folder/(case+'_model.json'), fitted)
            restored = read(folder/(case+'_model.json'))
            rows, probabilities = measure(selection_rows, restored)
            require(np.array_equal(model.predict(fitted, selection_rows[0]), probabilities[0])
                and np.array_equal(model.predict(restored, {**selection_rows[0], 'winner': -1}), probabilities[0]), 'D0_calibration_reload_or_result')
            models[case], scores[case] = restored, helper.summary(rows)
            joblib.dump(probabilities, folder/(case+'_selection_predictions.joblib'), compress=3)
            save(folder/(case+'_selection.json'), {'rows': rows, 'summary': scores[case], 'test_ids': [r['race_id'] for r in selection_rows]})
            print({'case': case, 'parameters': fitted['parameters'], 'selection': scores[case]}, flush=True)
        minimum = min(v['logloss'] for v in scores.values())
        chosen = next(c for c in model.CASES if scores[c]['logloss'] <= minimum+1e-8)
        save(folder/'selection.json', {'chosen': chosen, 'scores': scores, 'confirmation_used': False})
        save(folder/'final_calibrator.json', models[chosen])
        stage = 'confirmation'
        annual, all_rows, baseline_rows, market_rows = {}, [], [], []
        for year in (2024, 2025, 2026):
            subset = [r for r in records if r['race_date'].startswith(str(year))]
            a, probabilities = measure(subset, models[chosen])
            b, _ = measure(subset, models['K0'])
            market = [{**r, 'label': 'M0', 'loss': float(-np.log(source['q'][source['winner']])),
                       'hit': int(np.argmax(source['q']) == source['winner']),
                       'brier': float((source['q']@source['q']-2*source['q'][source['winner']]+1)/len(source['q']))}
                       for r, source in zip(b, subset, strict=True)]
            joblib.dump(probabilities, folder/f'{year}_selected_predictions.joblib', compress=3)
            save(folder/f'{year}_selected.json', {'rows': a, 'test_ids': [r['race_id'] for r in subset]})
            annual[str(year)] = {k: helper.grouped(v) for k, v in [('selected', a), ('D0', b), ('market', market)]}
            all_rows.extend(a)
            baseline_rows.extend(b)
            market_rows.extend(market)
        a, b = helper.summary(all_rows), helper.summary(baseline_rows)
        ci = helper.comparison_ci(all_rows, baseline_rows)
        checks = {'pooled_loss_better_than_D0': a['logloss'] < b['logloss'],
            'pooled_D0_loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
            'market_loss_better_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in annual.values()),
            'pooled_hit_rate_not_worse_than_D0': a['hit_rate'] >= b['hit_rate']}
        save(folder/'assessment.json', {'selected': chosen, 'confirmation': annual, 'pooled_selected': a, 'pooled_D0': b,
            'vs_D0_ci': ci, 'vs_market_ci': helper.comparison_ci(all_rows, market_rows), 'additional_promising_checks': checks,
            'replace_D0_as_research_candidate': all(checks.values()), 'production_adoption': False, 'unknown_test': False})
        require(sources() == initial and all(sha(ROOT/p) == v for p, v in initial.items()), 'D0_calibration_source_changed')
        save(folder/'manifest.json', {'status': 'complete', 'selected': chosen, 'source_sha256': initial,
            'final_calibrator_sha256': sha(folder/'final_calibrator.json'), 'assessment_sha256': sha(folder/'assessment.json'),
            'input_sha256': sha(folder/'inputs.joblib'), 'D0_refits': 0})
        print({'selected': chosen, 'parameters': models[chosen]['parameters'], 'checks': checks, 'pooled': a, 'D0': b})
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
