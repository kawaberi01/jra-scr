"""概要: D0の低確率側の弱点を、係数固定の特徴/条件差分除去で診断する。
作成日: 2026-10-25
入力: spec385、元D0 dataset/model、spec380の保存p。
出力: 新規runの年別/群別の全除去指標と基準一致証跡。
実行例: uv run --frozen --extra ml python scripts/diagnose_jra_d0_blocks.py --output artifacts/jra_research/d0_block_diagnostic_20261025
注意事項: 除去案を採用しない。再学習/SQL/HTTP/予想変更なし。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np

import run_jra_d0_calibration as runner

BLOCKS = {'market_shape': [0], 'cross_market': [1, 32, 33], 'clock': [2, 3, 4, 17, 18, 19],
    'opponent': [5, 6, 20, 21], 'aptitude': [7, 8, 9, 10, 22, 23, 24, 25],
    'rotation': list(range(11, 17))+list(range(26, 32)), 'attributes': list(range(34, 46))}
CONTEXTS = ('sd', 'cs', 'csd', 'season', 'csds')


def normalized(z):
    """最大値を引いた独立softmaxで正規化する。"""
    p = np.exp(z-max(z))
    return p/p.sum()


def summarize(rows):
    """同じ競走集合の基準と全12除去の平均損失・的中を集計する。"""
    return {'races': len(rows), 'cases': {case: {'logloss': float(np.mean([r['cases'][case]['loss'] for r in rows])),
            'hits': sum(r['cases'][case]['hit'] for r in rows)} for case in rows[0]['cases']}} if rows else {'races': 0}


def run(folder):
    """基準分布を照合して各除去を記述し、採用判断や係数変更をしない。"""
    folder.mkdir(parents=True, exist_ok=False)
    try:
        assert sorted(v for cols in BLOCKS.values() for v in cols) == list(range(46))
        source = runner.ROOT/'artifacts/jra_research/d0_calibration_20261025'
        manifest = runner.read(source/'manifest.json')
        assert runner.sha(source/'inputs.joblib') == manifest['input_sha256']
        saved = {r['race_id']: r for r in joblib.load(source/'inputs.joblib')}
        data = joblib.load(runner.REFERENCE/'dataset.joblib')
        original = data['records']+data['later']
        assert runner.sha(runner.REFERENCE/'dataset.joblib') == runner.read(runner.REFERENCE/'model-manifest.json')['dataset_sha256']
        rows, checked, model_hashes = [], 0, {}
        for year in (2023, 2024, 2025, 2026):
            fitted = runner.previous.reference(year)
            path = runner.REFERENCE/('final_model.joblib' if year == 2026 else f'{year}_D0.joblib')
            model_hashes[str(path.relative_to(runner.ROOT))] = runner.sha(path)
            for r in original:
                if not r['race_date'].startswith(str(year)):
                    continue
                group = 'nakayama_turf_1801_2200' if r['course'] == 6 and r['surface'] == 0 and r['distance'] > 1800 and r['distance'] <= 2200 else (
                    'kyoto_turf_2601_plus' if r['course'] == 8 and r['surface'] == 0 and r['distance'] > 2600 else None)
                if group is None:
                    continue
                x = runner.previous.model.base.matrix(r, 'D0')/fitted['scale'].astype(np.float32)
                active = [c for c in runner.previous.model.base.core.base.contexts(r, 'C2') if c in fitted['contexts']]
                beta = fitted['coef'][0].copy()
                for c in active:
                    beta += fitted['coef'][fitted['contexts'].index(c)]
                z = np.log(r['market'])+x @ beta
                baseline = normalized(z)
                assert np.allclose(baseline, saved[r['race_id']]['p'], rtol=1e-12, atol=1e-14)
                checked += 1
                variants = {'D0': baseline}
                for block, cols in BLOCKS.items():
                    variants['without_'+block] = normalized(z-x[:, cols] @ beta[cols])
                for context in CONTEXTS:
                    subtract = np.zeros(len(z))
                    for c in active:
                        if c.split(':')[0] == context:
                            subtract += x @ fitted['coef'][fitted['contexts'].index(c)]
                    variants['without_context_'+context] = normalized(z-subtract)
                y = r['winner']
                rows.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'group': group,
                    'true_D0_probability_under_001': bool(baseline[y] < .01), 'active_contexts': active,
                    'cases': {name: {'loss': float(-np.log(p[y])), 'hit': int(np.argmax(p) == y)} for name, p in variants.items()}})
        summaries = {}
        for group in ('nakayama_turf_1801_2200', 'kyoto_turf_2601_plus'):
            subset = [r for r in rows if r['group'] == group]
            confirmation = [r for r in subset if r['race_date'] >= '2024-01-01']
            summaries[group] = {'all': summarize(subset), 'confirmation': summarize(confirmation),
                'years': {str(y): summarize([r for r in subset if r['race_date'].startswith(str(y))]) for y in (2023, 2024, 2025, 2026)},
                'confirmation_tail_under_001': summarize([r for r in confirmation if r['true_D0_probability_under_001']])}
        runner.save(folder/'diagnostic.json', {'rows': rows, 'summaries': summaries, 'purpose': 'frozen_coefficient_description_no_selection'})
        runner.save(folder/'verification.json', {'status': 'passed', 'baseline_distributions_equal': checked,
            'feature_columns_partition': 46, 'ablations_per_race': 12, 'base_model_sha256': model_hashes,
            'D0_refits': 0, 'prediction_changes': 0})
        for group, values in summaries.items():
            baseline = values['confirmation']['cases']['D0']['logloss']
            print({'group': group, 'races': values['confirmation']['races'],
                'loss_decrease_when_removed': {k: round(baseline-v['logloss'], 6) for k, v in values['confirmation']['cases'].items() if k != 'D0'}})
    except Exception as error:
        runner.save(folder/'failure.json', {'type': type(error).__name__, 'stage': 'frozen_block_diagnostic'})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
