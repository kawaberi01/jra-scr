"""概要: 順位追加研究の全分布・選抜・教師境界・H2置換判定を別式で照合する。
作成日: 2026-10-24
入力: spec360研究run、保存済みH2/派生特徴。
出力: independent-verification.json、成功0/矛盾時非0。
実行例: uv run --frozen --extra ml python scripts/verify_jra_rank_chimera.py --run artifacts/jra_research/market_rank_chimera_20261024
注意事項: SQL/HTTP/再学習/実購入なし。独立した計算であって未知性能試験ではない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_rank_chimera as runner
from verify_jra_market_chimera import independent_predict


def probabilities(fitted, record):
    """旧独立H2式を再利用し、順位モデルまたは市場混合を別実装で再現する。"""
    p = independent_predict(fitted['base_model'], record)
    w = fitted['market_mix_weight']
    return w*p+(1-w)*record['market']


def verify(folder):
    """全セル・最終モデルの分布と、2023選抜/3年確認の結論を照合する。

    Raises:
        AssertionError: 入力SHA、確率、期間、選抜、比較判定の不一致。
    Notes:
        元モデル/成果物は変更せず、検証JSONのみ新規作成する。
    """
    read, prior = runner.read, runner.old.prior
    manifest, protocol = read(folder/'model-manifest.json'), read(folder/'protocol.json')
    assert not (folder/'failure.json').exists()
    assert prior.sha(folder/'final_model.joblib') == manifest['model_sha256']
    assert prior.sha(folder/'assessment.json') == manifest['assessment_sha256']
    assert all(prior.sha(runner.ROOT/p) == v for p, v in protocol['source_sha256'].items())
    assert prior.sha(runner.BASE/'dataset.joblib') == protocol['dataset_sha256']
    assert prior.sha(runner.LATER/'dataset.joblib') == protocol['later_dataset_sha256']
    records = joblib.load(runner.BASE/'dataset.joblib')['records']
    later = joblib.load(runner.LATER/'dataset.joblib')['records']
    by_id = {r['race_id']: r for r in records+later}
    saved_rows, count, cells = {}, 0, 0
    for path in folder.glob('*.json'):
        match = re.fullmatch(r'(2023|2024|2025)_(H2|G50|R25|R50|R100)\.json', path.name)
        if match is None:
            continue
        year, case = match.groups()
        cell = read(path)
        fitted = joblib.load(path.with_suffix('.joblib'))
        assert prior.sha(path.with_suffix('.joblib')) == cell['model_sha256']
        train = [r for r in records if r['race_date'] < year+'-01-01']
        assert cell['train_ids'] == [r['race_id'] for r in train]
        assert fitted['base_model']['train_races'] == len(train)
        assert fitted['base_model']['trained_through'] == max(r['race_date'] for r in train) < year+'-01-01'
        predictions = joblib.load(folder/f'{year}_{case}_predictions.joblib')
        assert len(predictions) == len(cell['test_ids']) == len(cell['rows'])
        for key, row, p in zip(cell['test_ids'], cell['rows'], predictions, strict=True):
            record = by_id[key]
            assert record['race_date'].startswith(year) and row['race_id'] == key
            expected = probabilities(fitted, record)
            assert np.allclose(p, expected, rtol=1e-12, atol=1e-14)
            assert abs(p.sum()-1) < 1e-12 and min(p) > 0
            assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
            assert int(np.argmax(p) == record['winner']) == row['hit']
            count += 1
        assert prior.summary(cell['rows']) == cell['summary']
        saved_rows[(year, case)] = cell['rows']
        cells += 1
    selection, assessment = read(folder/'selection.json'), read(folder/'assessment.json')
    scores = {c: prior.summary(saved_rows[('2023', c)]) for c in runner.model.ORDER}
    eligible = [c for c in runner.model.ORDER if scores[c]['logloss'] <= scores['H2']['logloss']+.005]
    max_hits = max(sum(r['hit'] for r in saved_rows[('2023', c)]) for c in eligible)
    winners = [c for c in eligible if sum(r['hit'] for r in saved_rows[('2023', c)]) == max_hits]
    minimum = min(scores[c]['logloss'] for c in winners)
    chosen = next(c for c in runner.model.ORDER if c in winners and scores[c]['logloss'] <= minimum+1e-8)
    assert chosen == selection['chosen'] == manifest['selected'] == assessment['selected']
    assert scores == selection['development'] and eligible == selection['eligible']
    final = joblib.load(folder/'final_model.joblib')
    assert manifest['train_ids'] == [r['race_id'] for r in records]
    assert final['base_model']['trained_through'] == max(r['race_date'] for r in records) < '2026-01-01'
    last = read(folder/'2026_selected.json')
    predictions = joblib.load(folder/'2026_selected_predictions.joblib')
    assert last['test_ids'] == [r['race_id'] for r in later]
    for record, p, row in zip(later, predictions, last['rows'], strict=True):
        assert np.allclose(p, probabilities(final, record), rtol=1e-12, atol=1e-14)
        assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
        assert int(np.argmax(p) == record['winner']) == row['hit']
        count += 1
    selected = saved_rows[('2024', chosen)]+saved_rows[('2025', chosen)]+last['rows']
    reference = saved_rows[('2024', 'H2')]+saved_rows[('2025', 'H2')]
    later_base, _ = runner.measure(later, runner.model.wrap(runner.load_reference(2026), 'H2'), 'H2')
    reference += later_base
    ci = prior.comparison_ci(selected, reference)
    assert ci == assessment['vs_H2_ci']
    pooled, base_pooled = prior.summary(selected), prior.summary(reference)
    assert pooled == assessment['pooled_selected'] and base_pooled == assessment['pooled_H2']
    annual = assessment['confirmation']
    checks = {'more_total_hits_than_H2': sum(r['hit'] for r in selected) > sum(r['hit'] for r in reference),
        'pooled_logloss_within_H2_plus_0.002': pooled['logloss'] <= base_pooled['logloss']+.002,
        'market_logloss_improves_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in annual.values()),
        'hit_rate_drop_within_half_pp_each_year': all(v['selected']['all']['hit_rate'] >= v['H2']['all']['hit_rate']-.005 for v in annual.values())}
    assert checks == assessment['replacement_checks']
    assert all(checks.values()) == assessment['replace_H2_as_research_candidate']
    output = {'status': 'passed', 'independent_distributions': count, 'cells': cells, 'future_training_rows': 0,
        'selection_verified': True, 'training_ids_verified': True, 'replacement_gate_verified': True,
        'model_sha256': manifest['model_sha256'], 'unknown_test': False}
    prior.save(folder/'independent-verification.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    verify(parser.parse_args().run)
