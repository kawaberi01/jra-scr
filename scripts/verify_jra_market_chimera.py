"""概要: 市場基準キメラの確率式・時系列・開発選抜・見込み判定を独立照合する。
作成日: 2026-10-24
入力: spec355研究runの派生特徴・セルモデル・保存全分布。
出力: independent-verification.json、成功0/矛盾時非0。
実行例: uv run --frozen --extra ml python scripts/verify_jra_market_chimera.py --run artifacts/jra_research/market_condition_chimera_20261024
注意事項: 自作joblibのみ読取。SQL/HTTP/再学習/実購入なし。未知試験ではない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_market_chimera as runner


def independent_predict(fitted, record):
    """本体のmatrix/contexts/predictを使わず、市場offset式を再構成する。"""
    q, pl = np.asarray(record['market']), np.asarray(record['pl'])
    gap = np.clip(np.log(pl/q), -10, 10)
    x = np.log(q)[:, None]
    if fitted['case'] != 'T0':
        x = np.column_stack((x, gap))
    if fitted['case'].startswith('H'):
        horse = np.asarray(record['x'], dtype=np.float32)
        ij = np.asarray(list(combinations(range(len(horse)), 2)))
        a, b = horse[ij[:, 0]], horse[ij[:, 1]]
        hx = np.column_stack(((a+b)/2, np.abs(a-b)))
        hx -= hx.mean(axis=0)
        x = np.column_stack((x, hx))
        if fitted['case'] == 'H2':
            x = np.column_stack((x, gap*np.mean(horse[ij, 0], axis=1), gap*np.mean(horse[ij, 9], axis=1)))
    x -= q @ x
    x = x.astype(np.float32)/fitted['scale'].astype(np.float32)
    c, t = int(record['course']), int(record['surface'])
    d = sum(int(record['distance']) > edge for edge in (1400, 1800, 2200, 2600))
    s = (int(record['race_date'][5:7]) % 12)//3
    names = [] if fitted['case'] in ('T0', 'P0', 'H0') else [f'sd:{t}:{d}', f'cs:{c}:{t}', f'csd:{c}:{t}:{d}', f'season:{s}', f'csds:{c}:{t}:{d}:{s}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    z = np.log(q)+x @ beta
    p = np.exp(z-max(z))
    return p/p.sum()


def verify(folder):
    """全セルの保存予測・訓練ID・選抜と最終係数/性能判定を照合する。"""
    read = runner.prior.features.read_json
    manifest, protocol = read(folder/'model-manifest.json'), read(folder/'protocol.json')
    assert not (folder/'failure.json').exists()
    assert runner.prior.sha(folder/'final_model.joblib') == manifest['model_sha256']
    assert runner.prior.sha(folder/'dataset.joblib') == manifest['dataset_sha256']
    assert runner.prior.sha(folder/'assessment.json') == manifest['assessment_sha256']
    assert all(runner.prior.sha(runner.ROOT/p) == v for p, v in manifest['source_sha256'].items())
    dataset = joblib.load(folder/'dataset.joblib')['records']
    by_id = {r['race_id']: r for r in dataset}
    selection, assessment = read(folder/'selection.json'), read(folder/'assessment.json')
    minimum = min(v['logloss'] for v in selection['development'].values())
    chosen = next(c for c in runner.model.CASES if selection['development'][c]['logloss'] <= minimum+1e-8)
    assert chosen == selection['chosen'] == manifest['selected_case'] == assessment['selected']
    cells, distributions = 0, 0
    rows_by_year = {}
    for path in sorted(folder.glob('*.json')):
        match = re.fullmatch(r'(2023|2024|2025)_(T0|P0|H0|H1|H2)\.json', path.name)
        if match is None:
            continue
        cell = read(path)
        year, case = match.groups()
        fitted = joblib.load(path.with_suffix('.joblib'))
        assert runner.prior.sha(path.with_suffix('.joblib')) == cell['model_sha256']
        train = [r for r in dataset if r['race_date'] < year+'-01-01']
        assert cell['train_ids'] == [r['race_id'] for r in train]
        assert fitted['trained_through'] == max(r['race_date'] for r in train) < year+'-01-01'
        assert fitted['train_races'] == len(train)
        pred = joblib.load(folder/f'{year}_{case}_predictions.joblib')
        assert len(pred) == len(cell['test_ids']) == len(cell['rows'])
        for key, row, p in zip(cell['test_ids'], cell['rows'], pred, strict=True):
            record = by_id[key]
            assert record['race_date'].startswith(year)
            independent = independent_predict(fitted, record)
            assert np.allclose(p, independent, rtol=1e-12, atol=1e-14)
            assert abs(p.sum()-1) < 1e-12 and min(p) > 0
            assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
            assert int(np.argmax(p) == record['winner']) == row['hit']
            distributions += 1
        summary = runner.prior.summary(cell['rows'])
        assert summary == cell['summary']
        if year == '2023':
            assert summary == selection['development'][case]
        else:
            assert summary == assessment['confirmation'][year][case]['all']
            rows_by_year[(year, case)] = cell['rows']
        cells += 1
    final = joblib.load(folder/'final_model.joblib')
    assert final['trained_through'] == max(r['race_date'] for r in dataset) < '2026-01-01'
    assert manifest['train_ids'] == [r['race_id'] for r in dataset]
    selected, markets, controls = [], [], []
    for year in ('2024', '2025'):
        selected.extend(rows_by_year[(year, chosen)])
        controls.extend(rows_by_year[(year, 'T0')])
        rows, _ = runner.measure([r for r in dataset if r['race_date'].startswith(year)], None, 'M0')
        markets.extend(rows)
    assert runner.prior.comparison_ci(selected, markets) == assessment['vs_market_ci']
    assert runner.prior.comparison_ci(selected, controls) == assessment['vs_calibrated_ci']
    summary, market = runner.prior.summary(selected), runner.prior.summary(markets)
    checks = {'market_logloss_improves_each_year': all(assessment['confirmation'][y][chosen]['all']['logloss'] < assessment['confirmation'][y]['M0']['all']['logloss'] for y in ('2024', '2025')),
        'pooled_market_loss_ci_positive': assessment['vs_market_ci']['loss_improvement_ci95'][0] > 0,
        'not_worse_than_calibration_each_year': all(assessment['confirmation'][y][chosen]['all']['logloss'] <= assessment['confirmation'][y]['T0']['all']['logloss'] for y in ('2024', '2025')),
        'hit_rate_drop_no_more_than_half_pp': summary['hit_rate'] >= market['hit_rate']-.005}
    assert checks == assessment['promising_checks']
    assert all(checks.values()) == assessment['promising_research_candidate']
    output = {'status': 'passed', 'cells': cells, 'independent_distributions': distributions, 'training_ids_verified': True,
              'no_future_training': True, 'selection_verified': True, 'bootstrap_comparisons': 2,
              'promising_gate_verified': True, 'model_sha256': manifest['model_sha256'], 'unknown_test': False}
    runner.prior.save(folder/'independent-verification.json', output)
    print(json.dumps(output))


def verify_later(folder, inputs, training_run):
    """2026追加確認を同じ独立式で照合し、固定候補と対照の差を検算する。"""
    read = runner.prior.features.read_json
    protocol, assessment = read(folder/'protocol.json'), read(folder/'assessment.json')
    source = read(inputs/'dataset-manifest.json')
    manifest = read(training_run/'model-manifest.json')
    assert runner.prior.sha(inputs/'dataset.joblib') == source['sha256'] == protocol['input_sha256']
    assert runner.prior.sha(training_run/'final_model.joblib') == manifest['model_sha256'] == protocol['model_sha256']
    records = joblib.load(inputs/'dataset.joblib')['records']
    ledger = read(folder/'ledger.json')
    checks = 0
    for case in ('selected', 'T0', 'P0'):
        fitted = joblib.load(training_run/'final_model.joblib' if case == 'selected' else folder/f'{case}.joblib')
        saved = joblib.load(folder/f'{case}_predictions.joblib')
        assert fitted['trained_through'] < min(r['race_date'] for r in records)
        assert fitted['train_races'] == manifest['train_races']
        assert len(saved) == len(records) == len(ledger[case])
        for record, row, p in zip(records, ledger[case], saved, strict=True):
            expected = independent_predict(fitted, record)
            assert record['race_id'] == row['race_id']
            assert np.allclose(p, expected, rtol=1e-12, atol=1e-14)
            assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
            assert int(np.argmax(p) == record['winner']) == row['hit']
            checks += 1
        assert runner.prior.summary(ledger[case]) == assessment['summaries'][case]['all']
    assert runner.prior.comparison_ci(ledger['selected'], ledger['market']) == assessment['vs_market_ci']
    assert runner.prior.comparison_ci(ledger['selected'], ledger['T0']) == assessment['vs_calibration_ci']
    assert runner.prior.comparison_ci(ledger['selected'], ledger['P0']) == assessment['vs_crossmarket_ci']
    output = {'status': 'passed', 'independent_distributions': checks, 'bootstrap_comparisons': 3,
              'fixed_candidate_not_reselected': True, 'future_training_rows': 0, 'input_sha_verified': True,
              'model_sha_verified': True, 'unknown_test': False}
    runner.prior.save(folder/'independent-verification.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--later-inputs', type=Path)
    parser.add_argument('--training-run', type=Path)
    args = parser.parse_args()
    if args.later_inputs:
        parser.error('--later-inputsには--training-runが必要です') if args.training_run is None else None
        verify_later(args.run, args.later_inputs, args.training_run)
    else:
        verify(args.run)
