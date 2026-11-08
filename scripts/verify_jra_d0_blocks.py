"""概要: D0固定係数寄与診断を独立行列と係数除去式で全件照合する。
作成日: 2026-10-25
入力: spec385診断dir、D0 datasetと年別係数。
出力: independent-verification.json。
実行例: uv run --frozen --extra ml python scripts/verify_jra_d0_blocks.py --run artifacts/jra_research/d0_block_diagnostic_20261025
注意事項: SQL/HTTP/再学習/候補選択なし。
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
from verify_jra_attribute_chimera import independent_matrix


def probability(coef, x, q):
    """係数を先に変更した別式で全分布を計算する。"""
    z = np.log(q)+x@coef
    p = np.exp(z-max(z))
    return p/p.sum()


def verify(folder):
    """全競走の基準と12除去、および全群集計を独立に検算する。"""
    data = runner.read(folder/'diagnostic.json')
    verification = runner.read(folder/'verification.json')
    assert not (folder/'failure.json').exists()
    assert all(runner.sha(runner.ROOT/p) == value for p, value in verification['base_model_sha256'].items())
    dataset = joblib.load(runner.REFERENCE/'dataset.joblib')
    records = {r['race_id']: r for r in dataset['records']+dataset['later']}
    models = {str(y): runner.previous.reference(y) for y in (2023, 2024, 2025, 2026)}
    blocks = {'market_shape': [0], 'cross_market': [1, 32, 33], 'clock': [2, 3, 4, 17, 18, 19],
        'opponent': [5, 6, 20, 21], 'aptitude': [7, 8, 9, 10, 22, 23, 24, 25],
        'rotation': list(range(11, 17))+list(range(26, 32)), 'attributes': list(range(34, 46))}
    count = 0
    for row in data['rows']:
        r = records[row['race_id']]
        fitted = models[r['race_date'][:4]]
        x = independent_matrix(r, 'D0')/fitted['scale'].astype(np.float32)
        band = sum(r['distance'] > v for v in (1400, 1800, 2200, 2600))
        season = (int(r['race_date'][5:7]) % 12)//3
        c, t = r['course'], r['surface']
        contexts = [v for v in (f'sd:{t}:{band}', f'cs:{c}:{t}', f'csd:{c}:{t}:{band}',
            f'season:{season}', f'csds:{c}:{t}:{band}:{season}') if v in fitted['contexts']]
        assert contexts == row['active_contexts']
        beta = fitted['coef'][0].copy()
        for name in contexts:
            beta += fitted['coef'][fitted['contexts'].index(name)]
        variants = {'D0': beta.copy()}
        for block, columns in blocks.items():
            coef = beta.copy()
            coef[columns] = 0
            variants['without_'+block] = coef
        for prefix in ('sd', 'cs', 'csd', 'season', 'csds'):
            coef = fitted['coef'][0].copy()
            for name in contexts:
                if name.split(':')[0] != prefix:
                    coef += fitted['coef'][fitted['contexts'].index(name)]
            variants['without_context_'+prefix] = coef
        assert set(variants) == set(row['cases'])
        for name, coef in variants.items():
            p = probability(coef, x, r['market'])
            value = row['cases'][name]
            assert abs(-np.log(p[r['winner']])-value['loss']) < 1e-12
            assert int(np.argmax(p) == r['winner']) == value['hit']
            count += 1
    summaries = 0
    for group, summary in data['summaries'].items():
        group_rows = [r for r in data['rows'] if r['group'] == group]
        sets = {'all': group_rows, 'confirmation': [r for r in group_rows if r['race_date'] >= '2024-01-01'],
                'confirmation_tail_under_001': [r for r in group_rows if r['race_date'] >= '2024-01-01' and r['true_D0_probability_under_001']]}
        for year in (2023, 2024, 2025, 2026):
            sets[str(year)] = [r for r in group_rows if r['race_date'].startswith(str(year))]
        for name, rows in sets.items():
            saved = summary['years'][name] if name.isdigit() else summary[name]
            assert saved['races'] == len(rows)
            if not rows:
                continue
            for case, metrics in saved['cases'].items():
                assert abs(math.fsum(r['cases'][case]['loss'] for r in rows)/len(rows)-metrics['logloss']) < 1e-12
                assert sum(r['cases'][case]['hit'] for r in rows) == metrics['hits']
                summaries += 1
    output = {'status': 'passed', 'independent_distributions': count, 'independent_summaries': summaries,
        'races': len(data['rows']), 'fits': 0, 'model_selection': False}
    runner.save(folder/'independent-verification.json', output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    verify(parser.parse_args().run)
