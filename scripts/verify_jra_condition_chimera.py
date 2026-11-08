"""概要: 条件別キメラの保存モデル・選抜・時系列評価を別の確率式で検算する。
作成日: 2026-10-24
入力: 完了した研究フォルダーと派生dataset.joblib。
出力: independent-verification.json、標準出力。矛盾時は非0で停止。
実行例: uv run --frozen --extra ml python scripts/verify_jra_condition_chimera.py --run artifacts/jra_research/condition_chimera_20261024
注意事項: 既知の自作joblibのみ対象。SQL/HTTP/再学習/実購入なし。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_condition_chimera as runner


def independent_probability(fitted, record):
    """本体のpair_matrix/contexts/predictを呼ばず、公開特徴から確率式を再構成する。"""
    horse = np.asarray(record['x'], dtype=np.float32)[:, fitted['columns']]
    ij = np.asarray(list(combinations(range(len(horse)), 2)))
    a, b = horse[ij[:, 0]], horse[ij[:, 1]]
    x = np.concatenate(((a+b)/2, np.abs(a-b)), axis=1)
    x -= np.mean(x, axis=0)
    x /= fitted['scale'].astype(np.float32)
    band = sum(int(record['distance']) > edge for edge in (1400, 1800, 2200, 2600))
    month = int(record['race_date'][5:7])
    s = (month % 12)//3
    c, t = int(record['course']), int(record['surface'])
    names = [] if fitted['case'] == 'C0' else [f'sd:{t}:{band}', f'cs:{c}:{t}', f'csd:{c}:{t}:{band}']
    if fitted['case'] == 'C2':
        names += [f'season:{s}', f'csds:{c}:{t}:{band}:{s}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    z = x @ beta
    p = np.exp(z-max(z))
    return p/p.sum()


def verify(folder):
    """全確認競走と3候補を再計算し、選抜/訓練境界/来歴/保存確率を照合する。"""
    read = runner.features.read_json
    manifest, protocol = read(folder/'model-manifest.json'), read(folder/'protocol.json')
    assert not (folder/'failure.json').exists()
    assert runner.sha(folder/'final_model.joblib') == manifest['model_sha256']
    assert runner.sha(folder/'assessment.json') == manifest['assessment_sha256']
    assert runner.sha(folder/'selection.json') == manifest['selection_sha256']
    assert all(runner.sha(runner.ROOT/path) == value for path, value in protocol['source_sha256'].items())
    dataset_path = folder/'dataset.joblib'
    if not dataset_path.exists():
        dataset_path = Path(read(folder/'reused-dataset.json')['path'])
    data_manifest = read(dataset_path.parent/'dataset-manifest.json')
    assert runner.sha(dataset_path) == data_manifest['sha256']
    records = joblib.load(dataset_path)['records']
    final = joblib.load(folder/'final_model.joblib')
    assert final['train_races'] == len(records) == len(manifest['training_race_ids'])
    assert manifest['training_race_ids'] == [r['race_id'] for r in records]
    assert final['trained_through'] == max(r['race_date'] for r in records) < '2026-01-01'
    selection, ledger, assessment = read(folder/'selection.json'), read(folder/'evaluation-ledger.json'), read(folder/'assessment.json')
    candidates = selection['development']
    minimum = min(v['logloss'] for v in candidates.values())
    chosen = next(c for c in ('C0', 'C1', 'C2') if candidates[c]['logloss'] <= minimum+1e-8)
    assert chosen == manifest['selected_case'] == final['case'] == assessment['chosen']
    train = [r for r in records if r['race_date'] < '2024-01-01']
    checks, summaries = 0, 0
    for case in ('C0', 'C1', 'C2'):
        fitted = joblib.load(folder/f'{case}.joblib')
        assert fitted['trained_through'] == max(r['race_date'] for r in train) < '2024-01-01'
        assert fitted['train_races'] == len(train)
        assert all(n >= 100 for c, n in fitted['context_counts'].items() if c in fitted['contexts'])
        for period, prefix in [('development', '2024'), ('confirmation', '2025')]:
            saved = ledger[period][case]
            selected = [r for r in records if r['race_date'].startswith(prefix)]
            assert len(saved) == len(selected)
            for record, row in zip(selected, saved, strict=True):
                assert record['race_id'] == row['race_id']
                p = independent_probability(fitted, record)
                assert abs(p.sum()-1) < 1e-12 and min(p) > 0
                assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-11
                assert int(np.argmax(p) == record['winner']) == row['hit']
                expected = (p@p-2*p[record['winner']]+1)/len(p)
                assert abs(expected-row['brier']) < 1e-12
                checks += 1
            values = runner.summary(saved)
            expected = candidates[case] if period == 'development' else assessment['confirmation'][case]['all']
            assert values == expected
            summaries += 1
    for block in runner.model.BLOCKS:
        fitted = joblib.load(folder/f'without_{block}.joblib')
        assert fitted['case'] == chosen and fitted['omitted'] == block
        assert fitted['trained_through'] < '2024-01-01'
        assert all(i not in fitted['columns'] for i in runner.model.BLOCKS[block])
        for prefix, period in [('2024', 'development'), ('2025', 'confirmation')]:
            rows = []
            for record in (r for r in records if r['race_date'].startswith(prefix)):
                p = independent_probability(fitted, record)
                target = record['winner']
                rows.append({'race_date': record['race_date'], 'loss': float(-np.log(p[target])),
                             'hit': int(np.argmax(p) == target),
                             'brier': float((p@p-2*p[target]+1)/len(p))})
                checks += 1
            expected = assessment['ablations'][block][period]
            if period == 'confirmation':
                expected = expected['all']
            actual = runner.summary(rows)
            assert actual['races'] == expected['races'] and actual['days'] == expected['days']
            for key in ('logloss', 'hit_rate', 'brier'):
                assert abs(actual[key]-expected[key]) < 1e-11
            summaries += 1
    sample = read(folder/'sample_input.json')
    output = read(folder/'sample_forecast.json')
    p = independent_probability(final, sample)
    positions = {tuple(v): i for i, v in enumerate(combinations(sample['horses'], 2))}
    assert len(p) == len(output['pair_ranking'])
    for row in output['pair_ranking']:
        assert abs(p[positions[tuple(row['horses'])]]-row['probability']) < 1e-12
    assert abs(sum(r['top2_probability'] for r in output['horse_ranking'])-2) < 1e-12
    value = {'status': 'passed', 'independent_probability_rows': checks, 'summary_checks': summaries,
             'selection_matches': True, 'training_ids_match': True, 'future_training_rows': 0,
             'final_model_sha256': manifest['model_sha256'], 'source_sha_unchanged': True,
             'unknown_performance_trial': False, 'production_adoption': False}
    runner.save(folder/'independent-verification.json', value)
    print(json.dumps(value))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    verify(parser.parse_args().run)
