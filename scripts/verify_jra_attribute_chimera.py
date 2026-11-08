"""概要: 当日属性の元カード結合と、追加モデルの全確率/選抜/追加有望判定を別式で検算する。
作成日: 2026-10-24
入力: spec365研究runの属性付dataset、保存カード、全セルと最終モデル。
出力: independent-verification.json。成功0、矛盾時は非0。
実行例: uv run --frozen --extra ml python scripts/verify_jra_attribute_chimera.py --run artifacts/jra_research/market_attribute_chimera_20261024_v3
注意事項: SQL/HTTP/再学習/実購入なし。既使用過去なので未知試験ではない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gzip
from itertools import combinations
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_attribute_chimera as runner
from verify_jra_market_chimera import independent_predict as old_independent


def independent_matrix(record, case):
    """追加行列の属性/連続距離/条件相互作用を本体関数なしで再構成する。"""
    q, pl = np.asarray(record['market']), np.asarray(record['pl'])
    gap = np.clip(np.log(pl/q), -10, 10)
    horse = np.asarray(record['x'], dtype=np.float32)
    ij = np.asarray(list(combinations(range(len(horse)), 2)))
    a, b = horse[ij[:, 0]], horse[ij[:, 1]]
    hx = np.column_stack(((a+b)/2, np.abs(a-b)))
    hx -= hx.mean(axis=0)
    base = np.column_stack((np.log(q), gap, hx, gap*np.mean(horse[ij, 0], axis=1), gap*np.mean(horse[ij, 9], axis=1)))
    base -= q @ base
    components = [base.astype(np.float32).astype(float)]
    attrs = np.asarray(record['attributes'], dtype=np.float32)
    a, b = attrs[ij[:, 0]], attrs[ij[:, 1]]
    components.append(np.column_stack(((a+b)/2, np.abs(a-b))).astype(float))
    if case in ('D1', 'D2'):
        s = min(max((int(record['distance'])-2000)/1000, -1.2), 1.6)
        components.append(hx.astype(float)*s)
    if case == 'D2':
        short = horse[:, :9]
        a, b = short[ij[:, 0]], short[ij[:, 1]]
        values = np.column_stack(((a+b)/2, np.abs(a-b)))
        values -= values.mean(axis=0)
        components.extend(values.astype(float)*flag for flag in record['race_flags'])
    x = np.column_stack(components)
    x -= q @ x
    return x.astype(np.float32)


def independent_predict(fitted, record):
    """旧H2と新属性モデルをそれぞれの独立式で推論する。"""
    if fitted['protocol'] == runner.model.core.PROTOCOL:
        return old_independent(fitted, record)
    x = independent_matrix(record, fitted['case'])/fitted['scale'].astype(np.float32)
    c, t = int(record['course']), int(record['surface'])
    d = sum(int(record['distance']) > edge for edge in (1400, 1800, 2200, 2600))
    s = (int(record['race_date'][5:7]) % 12)//3
    names = [f'sd:{t}:{d}', f'cs:{c}:{t}', f'csd:{c}:{t}:{d}', f'season:{s}', f'csds:{c}:{t}:{d}:{s}']
    beta = fitted['coef'][0].copy()
    for name in names:
        if name in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(name)]
    z = np.log(record['market'])+x @ beta
    p = np.exp(z-max(z))
    return p/p.sum()


def verify_attributes(records, manifest):
    """7年の元カードから全追加属性を独立に結合し、欠測表示と件数を照合する。

    Returns:
        検査した出走行数と競走数。
    Raises:
        AssertionError: 元SHA、性齢、枠欠測、競走条件、馬集合の不一致。
    """
    wanted = {r['race_id']: r for r in records}
    checked, runner_count = set(), 0
    for year in range(2020, 2027):
        path = runner.CARDS/str(year)/'races.jsonl.gz'
        assert runner.sha(path) == manifest['card_sha256'][str(path.relative_to(runner.ROOT))]
        missing = 0
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                source = json.loads(line)
                if source['race_id'] not in wanted:
                    continue
                record = wanted[source['race_id']]
                rows = {f"{int(v['horse_no']):02d}": v for v in source['inputs']['runners'] if str(v['horse_no']).isdigit()}
                flags = []
                values = []
                for number in record['horses']:
                    row = rows[number]
                    label = row['sex_age']
                    age = int(re.search(r'\d+', label)[0])/10
                    female = int(label.startswith('牝'))
                    gelding = int(label.startswith(('セ', 'せん', '騸')))
                    frame = row.get('frame_no')
                    known = frame is not None and str(frame).isdigit() and 1 <= int(frame) <= 8
                    values.append([age, female, gelding, int(frame)/8 if known else .5,
                                   int(number)/len(record['horses']), int(not known)])
                    h = row['history_features']
                    flags.append([h[k] for k in ('is_newcomer', 'is_maiden', 'is_open_or_stakes')])
                    missing += int(not known)
                    runner_count += 1
                np.testing.assert_array_equal(np.asarray(values, dtype=np.float32), record['attributes'])
                assert all(flag == flags[0] for flag in flags)
                np.testing.assert_array_equal(np.asarray(flags[0], dtype=np.float32), record['race_flags'])
                checked.add(source['race_id'])
        assert missing == manifest['coverage'][str(year)]['missing_frames']
    assert checked == set(wanted)
    return runner_count, len(checked)


def verify(folder):
    """入力結合・全モデルの保存確率・教師期間・選抜と置換判定を照合する。"""
    manifest, protocol = runner.read(folder/'model-manifest.json'), runner.read(folder/'protocol.json')
    assert not (folder/'failure.json').exists()
    assert runner.sha(folder/'final_model.joblib') == manifest['model_sha256']
    assert runner.sha(folder/'dataset.joblib') == manifest['dataset_sha256']
    assert runner.sha(folder/'assessment.json') == manifest['assessment_sha256']
    assert all(runner.sha(runner.ROOT/p) == v for p, v in protocol['source_sha256'].items())
    data = joblib.load(folder/'dataset.joblib')
    records, later = data['records'], data['later']
    input_manifest = runner.read(folder/'dataset-manifest.json')
    attrs, races = verify_attributes(records+later, input_manifest)
    by_id = {r['race_id']: r for r in records+later}
    counts, cells, saved_rows = 0, 0, {}
    for path in folder.glob('*.json'):
        match = re.fullmatch(r'(2023|2024|2025)_(H2|D0|D1|D2)\.json', path.name)
        if match is None:
            continue
        year, case = match.groups()
        cell = runner.read(path)
        fitted = joblib.load(path.with_suffix('.joblib'))
        assert runner.sha(path.with_suffix('.joblib')) == cell['model_sha256']
        train = [r for r in records if r['race_date'] < year+'-01-01']
        assert cell['train_ids'] == [r['race_id'] for r in train]
        assert fitted['train_races'] == len(train)
        assert fitted['trained_through'] == max(r['race_date'] for r in train) < year+'-01-01'
        probabilities = joblib.load(folder/f'{year}_{case}_predictions.joblib')
        for key, row, p in zip(cell['test_ids'], cell['rows'], probabilities, strict=True):
            record = by_id[key]
            assert record['race_date'].startswith(year)
            assert np.allclose(p, independent_predict(fitted, record), rtol=1e-12, atol=1e-14)
            assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
            assert int(np.argmax(p) == record['winner']) == row['hit']
            counts += 1
        assert runner.previous.old.prior.summary(cell['rows']) == cell['summary']
        saved_rows[(year, case)] = cell['rows']
        cells += 1
    selection, assessment = runner.read(folder/'selection.json'), runner.read(folder/'assessment.json')
    scores = {c: runner.previous.old.prior.summary(saved_rows[('2023', c)]) for c in runner.ORDER}
    minimum = min(v['logloss'] for v in scores.values())
    selected = next(c for c in runner.ORDER if scores[c]['logloss'] <= minimum+1e-8)
    assert selected == selection['chosen'] == assessment['selected'] == manifest['selected']
    final = joblib.load(folder/'final_model.joblib')
    assert manifest['train_ids'] == [r['race_id'] for r in records]
    assert final['trained_through'] == max(r['race_date'] for r in records) < '2026-01-01'
    last = runner.read(folder/'2026_selected.json')
    probabilities = joblib.load(folder/'2026_selected_predictions.joblib')
    assert last['test_ids'] == [r['race_id'] for r in later]
    for record, row, p in zip(later, last['rows'], probabilities, strict=True):
        assert np.allclose(p, independent_predict(final, record), rtol=1e-12, atol=1e-14)
        assert abs(-np.log(p[record['winner']])-row['loss']) < 1e-12
        assert int(np.argmax(p) == record['winner']) == row['hit']
        counts += 1
    candidate = saved_rows[('2024', selected)]+saved_rows[('2025', selected)]+last['rows']
    baseline = saved_rows[('2024', 'H2')]+saved_rows[('2025', 'H2')]
    more, _ = runner.measure(later, runner.previous.load_reference(2026), 'H2')
    baseline.extend(more)
    helper = runner.previous.old.prior
    ci = helper.comparison_ci(candidate, baseline)
    assert ci == assessment['vs_H2_ci']
    a, b = helper.summary(candidate), helper.summary(baseline)
    assert a == assessment['pooled_selected'] and b == assessment['pooled_H2']
    checks = {'pooled_loss_better_than_H2': a['logloss'] < b['logloss'],
        'pooled_H2_loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
        'market_loss_better_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in assessment['confirmation'].values()),
        'pooled_hit_rate_not_worse_than_H2': a['hit_rate'] >= b['hit_rate']}
    assert checks == assessment['additional_promising_checks']
    assert all(checks.values()) == assessment['replace_H2_as_research_candidate']
    output = {'status': 'passed', 'source_card_attribute_rows': attrs, 'attribute_races': races,
        'independent_distributions': counts, 'cells': cells, 'selection_verified': True, 'future_training_rows': 0,
        'source_model_sha_verified': True, 'replacement_gate_verified': True, 'unknown_test': False}
    runner.save(folder/'independent-verification.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    verify(parser.parse_args().run)
