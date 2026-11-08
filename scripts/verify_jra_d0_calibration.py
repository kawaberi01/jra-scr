"""概要: D0校正の全分布・係数最適性・期間分離・診断・選択と更新判定を別式照合する。
作成日: 2026-10-25
入力: spec380成功runと保存済みp/q入力。
出力: independent-verification.json。
実行例: uv run --frozen --extra ml python scripts/verify_jra_d0_calibration.py --run artifacts/jra_research/d0_calibration_20261025
注意事項: SQL/HTTP/D0再学習/校正再fitなし。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import math
from pathlib import Path

import joblib
import numpy as np

import run_jra_d0_calibration as runner


def independent(fitted, record):
    """本体transform/predictを使わず5構成の確率を再計算する。"""
    p, q = record['p'], record['q']
    case, parameters = fitted['case'], fitted['parameters']
    if case == 'K0':
        return p.copy()
    if case == 'KM':
        return p+parameters['e']*(q-p)
    if case == 'KT':
        z = parameters['t']*np.log(p)
    else:
        a = parameters['a'] if case == 'KR' else parameters['high' if max(p) >= .2 else 'low']
        z = (1-a)*np.log(q)+a*np.log(p)
    out = np.exp(z-max(z))
    return out/out.sum()


def gradient(fitted, records, key):
    """凸な1変数損失の解析勾配で、保存係数の最適性を再fitなしで検査する。"""
    values = []
    for r in records:
        calibrated = independent(fitted, r)
        y, case = r['winner'], fitted['case']
        if case == 'KM':
            values.append((r['p'][y]-r['q'][y])/calibrated[y])
        else:
            x = np.log(r['p']) if case == 'KT' else np.log(r['p'])-np.log(r['q'])
            values.append(float(calibrated@x-x[y]))
    value = float(np.mean(values))
    v = fitted['parameters'][key]
    lo, hi = (.7, 1.3) if fitted['case'] == 'KT' else ((0, .5) if fitted['case'] == 'KM' else (0, 1))
    assert lo <= v <= hi
    assert value >= -1e-6 if abs(v-lo) < 1e-7 else (value <= 1e-6 if abs(v-hi) < 1e-7 else abs(value) < 1e-5)
    return value


def check_cell(records, rows, probabilities, fitted):
    """保存全分布と損失/的中/Brier、正解遮断対象日を別計算する。"""
    for r, row, actual in zip(records, rows, probabilities, strict=True):
        assert r['race_id'] == row['race_id'] and fitted['trained_through'] < r['race_date']
        assert np.allclose(independent(fitted, r), actual, rtol=1e-12, atol=1e-14)
        y = r['winner']
        assert abs(-np.log(actual[y])-row['loss']) < 1e-12
        assert int(np.argmax(actual) == y) == row['hit']
        assert abs((actual@actual-2*actual[y]+1)/len(actual)-row['brier']) < 1e-12
    return len(records)


def verify(folder):
    """校正と選抜の分離、全8セルと区間/更新条件を独立に照合する。"""
    read, sha = runner.read, runner.sha
    manifest, protocol = read(folder/'manifest.json'), read(folder/'protocol.json')
    assert manifest['status'] == 'complete' and not (folder/'failure.json').exists()
    assert all(sha(runner.ROOT/p) == value for p, value in manifest['source_sha256'].items())
    assert sha(folder/'inputs.joblib') == manifest['input_sha256']
    assert sha(folder/'assessment.json') == manifest['assessment_sha256']
    assert sha(folder/'final_calibrator.json') == manifest['final_calibrator_sha256']
    inputs = read(folder/'input-manifest.json')
    assert all(sha(runner.ROOT/p) == value for p, value in inputs['source_prediction_sha256'].items())
    records = joblib.load(folder/'inputs.joblib')
    train = [r for r in records if '2023-01-01' <= r['race_date'] <= '2023-08-31']
    selection = [r for r in records if '2023-09-01' <= r['race_date'] <= '2023-12-31']
    assert len({r['race_id'] for r in records}) == len(records)
    assert not set(r['race_id'] for r in train)&set(r['race_id'] for r in selection)
    scores, checked, gradients = {}, 0, {}
    for case in runner.model.CASES:
        fitted = read(folder/(case+'_model.json'))
        assert fitted['case'] == case and fitted['train_ids'] == [r['race_id'] for r in train]
        assert fitted['trained_through'] == max(r['race_date'] for r in train) < '2023-09-01'
        for key in fitted['parameters']:
            subset = train if case != 'KC' else [r for r in train if (max(r['p']) >= .2) == (key == 'high')]
            if case == 'KC':
                assert len(subset) == fitted['group_counts'][key]
            if len(subset) < 100 and case == 'KC':
                assert fitted['parameters'][key] == 1
            else:
                gradients[case+':'+key] = gradient(fitted, subset, key)
        cell = read(folder/(case+'_selection.json'))
        assert cell['test_ids'] == [r['race_id'] for r in selection]
        checked += check_cell(selection, cell['rows'], joblib.load(folder/(case+'_selection_predictions.joblib')), fitted)
        scores[case] = runner.helper.summary(cell['rows'])
        assert cell['summary'] == scores[case]
    minimum = min(v['logloss'] for v in scores.values())
    chosen = next(c for c in runner.model.CASES if scores[c]['logloss'] <= minimum+1e-8)
    final = read(folder/'final_calibrator.json')
    assert final == read(folder/(chosen+'_model.json'))
    selected = read(folder/'selection.json')
    assert chosen == selected['chosen'] == manifest['selected'] and selected['scores'] == scores
    candidate, baseline, market = [], [], []
    assessment = read(folder/'assessment.json')
    for year in (2024, 2025, 2026):
        subset = [r for r in records if r['race_date'].startswith(str(year))]
        cell = read(folder/f'{year}_selected.json')
        assert cell['test_ids'] == [r['race_id'] for r in subset]
        checked += check_cell(subset, cell['rows'], joblib.load(folder/f'{year}_selected_predictions.joblib'), final)
        a = cell['rows']
        b = [{**row, 'label': 'K0', 'loss': float(-np.log(r['p'][r['winner']])),
            'hit': int(np.argmax(r['p']) == r['winner']),
            'brier': float((r['p']@r['p']-2*r['p'][r['winner']]+1)/len(r['p']))} for r, row in zip(subset, a, strict=True)]
        m = [{**row, 'label': 'M0', 'loss': float(-np.log(r['q'][r['winner']])),
            'hit': int(np.argmax(r['q']) == r['winner']),
            'brier': float((r['q']@r['q']-2*r['q'][r['winner']]+1)/len(r['q']))} for r, row in zip(subset, a, strict=True)]
        for name, rows in [('selected', a), ('D0', b), ('market', m)]:
            assert runner.helper.grouped(rows) == assessment['confirmation'][str(year)][name]
        candidate.extend(a)
        baseline.extend(b)
        market.extend(m)
    a, b = runner.helper.summary(candidate), runner.helper.summary(baseline)
    ci = runner.helper.comparison_ci(candidate, baseline)
    assert a == assessment['pooled_selected'] and b == assessment['pooled_D0'] and ci == assessment['vs_D0_ci']
    assert runner.helper.comparison_ci(candidate, market) == assessment['vs_market_ci']
    checks = {'pooled_loss_better_than_D0': a['logloss'] < b['logloss'],
        'pooled_D0_loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
        'market_loss_better_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in assessment['confirmation'].values()),
        'pooled_hit_rate_not_worse_than_D0': a['hit_rate'] >= b['hit_rate']}
    assert checks == assessment['additional_promising_checks']
    assert all(checks.values()) == assessment['replace_D0_as_research_candidate']
    # 診断の核心を別の加算式で照合する。後年の群を校正に使っていない。
    rows = [r for r in records if r['race_date'] >= '2024-01-01' and r['course'] == 6 and r['surface'] == 0 and r['distance_band'] == 2]
    diagnostic = read(folder/'diagnostic.json')['nakayama_turf_1801_2200']
    for key, subset in [('confirmation', rows), ('true_D0_probability_under_001', [r for r in rows if r['p'][r['winner']] < .01])]:
        value = diagnostic[key]
        assert len(subset) == value['races']
        assert abs(math.fsum(math.log(r['q'][r['winner']]/r['p'][r['winner']]) for r in subset)-value['D0_minus_market_loss_sum']) < 1e-12
    output = {'status': 'passed', 'independent_distributions': checked, 'cells': 8,
        'calibration_races': len(train), 'selection_races': len(selection), 'overlap': 0,
        'analytic_optimality_gradients': gradients, 'selection_verified': True, 'replacement_gate_verified': True,
        'diagnostic_tail_loss_verified': True, 'calibrator_refits': 0, 'unknown_test': False}
    runner.save(folder/'independent-verification.json', output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    verify(parser.parse_args().run)
