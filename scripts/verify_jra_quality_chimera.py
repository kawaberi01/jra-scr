"""概要: 信頼度相互作用モデルの保存分布・教師境界・選抜と更新条件を別式照合する。
作成日: 2026-10-24
入力: spec370成功runとSHA固定のD0属性dataset。
出力: independent-verification.json。成功0、矛盾時非0。
実行例: uv run --frozen --extra ml python scripts/verify_jra_quality_chimera.py --run artifacts/jra_research/quality_chimera_20261024
注意事項: SQL/HTTP/再学習なし。元属性の成功済み全件検算は再実行しない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from itertools import combinations
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_quality_chimera as runner
from verify_jra_attribute_chimera import independent_matrix as D0_matrix, independent_predict as D0_predict


def independent_matrix(record, case):
    """本体のgate/matrixを使わず、64列の各値と中心化を再構築する。"""
    horse = np.asarray(record['x'], dtype=np.float32)
    if case == 'QH':
        count = np.expm1(5*horse[:, 9].astype(float))
        weight = count/(count+5)
    elif case == 'QR':
        weight = 90/(90+365*horse[:, 10].astype(float))
    else:
        assert case == 'QC'
        weight = (1-horse[:, 13].astype(float))*np.exp(-np.abs(horse[:, 12].astype(float))/2)
    values = (horse[:, :9]*weight[:, None]).astype(np.float32)
    ij = np.asarray(list(combinations(range(len(horse)), 2)))
    a, b = values[ij[:, 0]], values[ij[:, 1]]
    extra = np.column_stack(((a+b)/2, np.abs(a-b)))
    x = np.column_stack((D0_matrix(record, 'D0').astype(float), extra.astype(float)))
    x -= np.asarray(record['market']) @ x
    return x.astype(np.float32)


def independent_predict(fitted, record):
    """別式の64列と条件係数から確率分布を再計算する。"""
    if fitted['case'] == 'D0':
        return D0_predict(fitted, record)
    x = independent_matrix(record, fitted['case'])/fitted['scale'].astype(np.float32)
    c, t = int(record['course']), int(record['surface'])
    d = sum(int(record['distance']) > edge for edge in (1400, 1800, 2200, 2600))
    s = (int(record['race_date'][5:7]) % 12)//3
    names = [f'sd:{t}:{d}', f'cs:{c}:{t}', f'csd:{c}:{t}:{d}', f'season:{s}', f'csds:{c}:{t}:{d}:{s}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    logits = np.log(record['market'])+x @ beta
    p = np.exp(logits-max(logits))
    return p/p.sum()


def check_rows(records, rows, probabilities, fitted):
    """全分布と正解損失/的中/Brierを別計算し件数を返す。"""
    for r, row, p in zip(records, rows, probabilities, strict=True):
        assert row['race_id'] == r['race_id'] and row['race_date'] == r['race_date']
        expected = independent_predict(fitted, r)
        assert np.allclose(p, expected, rtol=1e-12, atol=1e-14)
        y = r['winner']
        assert abs(-np.log(p[y])-row['loss']) < 1e-12
        assert int(np.argmax(p) == y) == row['hit']
        assert abs((p@p-2*p[y]+1)/len(p)-row['brier']) < 1e-12
    return len(rows)


def verify(folder):
    """入力SHA・全教師ID・開発選抜・固定確認・更新判定を照合する。"""
    read, sha = runner.read, runner.sha
    protocol, manifest = read(folder/'protocol.json'), read(folder/'model-manifest.json')
    inputs, assessment = read(folder/'input-manifest.json'), read(folder/'assessment.json')
    assert not (folder/'failure.json').exists()
    assert all(sha(runner.ROOT/p) == value for p, value in protocol['source_sha256'].items())
    assert sha(folder/'assessment.json') == manifest['assessment_sha256']
    assert sha(folder/'final_model.joblib') == manifest['model_sha256']
    dataset = runner.ROOT/inputs['dataset']
    assert sha(dataset) == inputs['dataset_sha256'] == manifest['dataset_sha256']
    assert sha(runner.REFERENCE/'model-manifest.json') == inputs['reference_manifest_sha256']
    data = joblib.load(dataset)
    records, later = data['records'], data['later']
    by_id = {r['race_id']: r for r in records+later}
    rows_by_cell, checked, cells = {}, 0, 0
    for path in folder.glob('*.json'):
        match = re.fullmatch(r'(2023|2024|2025)_(D0|QH|QR|QC)\.json', path.name)
        if not match:
            continue
        year, case = match.groups()
        cell = read(path)
        fitted = joblib.load(path.with_suffix('.joblib'))
        assert sha(path.with_suffix('.joblib')) == cell['model_sha256']
        train = [r for r in records if r['race_date'] < year+'-01-01']
        assert cell['train_ids'] == [r['race_id'] for r in train]
        assert fitted['train_races'] == len(train) and fitted['case'] == case
        assert fitted['trained_through'] == max(r['race_date'] for r in train) < year+'-01-01'
        test = [r for r in records if r['race_date'].startswith(year)]
        assert cell['test_ids'] == [r['race_id'] for r in test]
        probabilities = joblib.load(folder/f'{year}_{case}_predictions.joblib')
        checked += check_rows(test, cell['rows'], probabilities, fitted)
        assert runner.helper.summary(cell['rows']) == cell['summary']
        rows_by_cell[(year, case)] = cell['rows']
        cells += 1
    selection = read(folder/'selection.json')
    scores = {case: runner.helper.summary(rows_by_cell[('2023', case)]) for case in runner.ORDER}
    minimum = min(v['logloss'] for v in scores.values())
    chosen = next(c for c in runner.ORDER if scores[c]['logloss'] <= minimum+1e-8)
    assert scores == selection['development']
    assert chosen == selection['chosen'] == manifest['selected'] == assessment['selected']
    final = joblib.load(folder/'final_model.joblib')
    assert manifest['train_ids'] == [r['race_id'] for r in records]
    assert final['train_races'] == len(records) and final['case'] == chosen
    assert final['trained_through'] == max(r['race_date'] for r in records) < '2026-01-01'
    last = read(folder/'2026_selected.json')
    assert last['test_ids'] == [r['race_id'] for r in later]
    checked += check_rows(later, last['rows'], joblib.load(folder/'2026_selected_predictions.joblib'), final)
    candidate = rows_by_cell[('2024', chosen)]+rows_by_cell[('2025', chosen)]+last['rows']
    baseline = rows_by_cell[('2024', 'D0')]+rows_by_cell[('2025', 'D0')]
    baseline_later, _ = runner.measure(later, runner.reference(2026), 'D0')
    baseline.extend(baseline_later)
    market, _ = runner.measure([by_id[r['race_id']] for r in candidate], None, 'M0')
    a, b = runner.helper.summary(candidate), runner.helper.summary(baseline)
    ci = runner.helper.comparison_ci(candidate, baseline)
    assert a == assessment['pooled_selected'] and b == assessment['pooled_D0'] and ci == assessment['vs_D0_ci']
    assert runner.helper.comparison_ci(candidate, market) == assessment['vs_market_ci']
    for year in ('2024', '2025', '2026'):
        for key, rows in [('selected', candidate), ('D0', baseline), ('market', market)]:
            assert runner.helper.grouped([r for r in rows if r['race_date'].startswith(year)]) == assessment['confirmation'][year][key]
    checks = {'pooled_loss_better_than_D0': a['logloss'] < b['logloss'],
        'pooled_D0_loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
        'market_loss_better_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in assessment['confirmation'].values()),
        'pooled_hit_rate_not_worse_than_D0': a['hit_rate'] >= b['hit_rate']}
    assert checks == assessment['additional_promising_checks']
    assert all(checks.values()) == assessment['replace_D0_as_research_candidate']
    output = {'status': 'passed', 'independent_distributions': checked, 'cells': cells,
        'teacher_ids_and_dates_verified': True, 'selection_verified': True, 'replacement_gate_verified': True,
        'source_dataset_model_sha_verified': True, 'refits': 0, 'unknown_test': False}
    runner.save(folder/'independent-verification.json', output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    verify(parser.parse_args().run)
