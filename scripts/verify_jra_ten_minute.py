"""概要: T10入力・16列・8モデルの全分布/精算/区間を独立検算する。
作成日: 2026-11-07
入力: 完了runと固定年別市場原本。
出力: 独立検算JSON。不一致時は例外。
実行例: uv run --frozen --extra ml python scripts/verify_jra_ten_minute.py
注意事項: 再学習・外部通信・SQL書込なし。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import datetime, timedelta
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np
from scipy.special import softmax
import run_jra_ten_minute as run
from verify_jra_current_attributes import independent_matrix
from verify_jra_purchase_operability import choose, statistics


def features(r, case):
    """別列挙のS0特徴と市場変化2列を同じfloat32境界で作る。"""
    current = independent_matrix(r)
    if case != 'M10':
        return current
    q = np.asarray(r['market'])
    extra = np.array([[np.clip(np.log(a / b), -5, 5), np.clip(np.log(c / d), -5, 5)]
                      for a, b, c, d in zip(q, r['early_market'], r['pl'], r['early_pl'], strict=True)])
    extra -= np.dot(q, extra)
    return np.column_stack((current, extra.astype(np.float32))).astype(np.float32)


def predict(fitted, r, case):
    """共有/条件係数を独立加算し全馬連softmaxを再計算する。"""
    beta = fitted['coef'][0].copy()
    for context in run.model.base.core.base.contexts(r, 'C2'):
        if context in fitted['contexts']:
            beta += fitted['coef'][fitted['contexts'].index(context)]
    return softmax(np.log(r['market']) + (features(r, case) / fitted['scale'].astype(np.float32)) @ beta)


def verify(folder):
    """原本T10照合、全モデル全分布・精算・時系列・日単位採否を確認する。"""
    manifest = run.read(folder / 'manifest.json')
    for group in ('source_sha256', 'frozen_inputs_sha256'):
        assert all(run.sha(run.ROOT / p) == h for p, h in manifest[group].items())
    assert all(run.sha(folder / p) == h for p, h in manifest['files_sha256'].items())
    records = joblib.load(folder / 'dataset.joblib')
    by_id = {r['race_id']: r for r in records}
    original = joblib.load(run.REF / 'dataset.joblib')
    old = {r['race_id']: r for r in original['records'] + original['later']}
    checked_inputs = 0
    for relative, digest in run.read(folder / 'dataset-manifest.json')['archive_sha256'].items():
        assert run.sha(run.ROOT / relative) == digest
        for raw in run.reuse.prior.readlines(run.ROOT / relative):
            key = raw['race_id']
            if key not in by_id:
                continue
            r = by_id[key]; o = old[key]
            quote = raw['inputs']['odds']['T-10m']
            cutoff = datetime.fromisoformat(raw['race']['start_at']) - timedelta(minutes=10)
            for market in quote.values():
                if isinstance(market, dict) and 'announced_at' in market:
                    assert datetime.fromisoformat(market['cutoff']) == cutoff
                    assert 0 <= (cutoff - datetime.fromisoformat(market['announced_at'])).total_seconds() <= 300
            qm = {tuple(sorted([int(p['horse_no_1']), int(p['horse_no_2'])])): p['odds'] for p in quote['quinella']['pairs']}
            prices = np.array([qm[p] for p in combinations(map(int, r['horses']), 2)])
            assert np.array_equal(prices, r['prices'])
            inv = 1 / prices; inv /= inv.sum()
            assert np.array_equal(inv, r['market']) and np.array_equal(r['early_market'], o['market'])
            wm = {int(v['horse_no']): v['odds'] for v in quote['win']['horses']}
            win = np.array([1 / wm[int(h)] for h in r['horses']]); win /= win.sum()
            pair = np.array([win[a] * win[b] * (1 / (1 - win[a]) + 1 / (1 - win[b])) for a, b in combinations(range(len(win)), 2)])
            pair /= pair.sum()
            assert np.allclose(pair, r['pl'], rtol=1e-12, atol=1e-14)
            assert np.array_equal(r['attributes'], o['attributes']) and r['winner'] == o['winner']
            assert np.array_equal(features(r, 'M10'), run.model.matrix(r))
            checked_inputs += 1
    assessment = run.read(folder / 'assessment.json')
    precision = run.read(folder / 'precision-rows.json')
    purchases = run.read(folder / 'purchase-rows.json')
    distributions, settlements = 0, 0
    accumulated = {case: [] for case in ('S0_direct', 'S10', 'M10')}
    for year in (2023, 2024, 2025, 2026):
        train = [r for r in records if r['race_date'] < f'{year}-01-01']
        test = [r for r in records if r['race_date'].startswith(str(year))]
        expected_ids = [r['race_id'] for r in test]
        for case in ('S0_direct', 'S10', 'M10'):
            fitted = joblib.load(run.reuse.prior.old.S0 / f'{year}_S0.joblib') if case == 'S0_direct' else joblib.load(folder / f'{year}_{case}.joblib')
            if case != 'S0_direct':
                cell = run.read(folder / f'{year}_{case}.json')
                assert cell['test_ids'] == expected_ids and cell['train_ids'] == [r['race_id'] for r in train]
                assert fitted['trained_through'] < min(r['race_date'] for r in test)
                assert cell['model_sha256'] == run.sha(folder / f'{year}_{case}.joblib')
            pp = joblib.load(folder / f'{year}_{case}_predictions.joblib')
            for r, p in zip(test, pp, strict=True):
                assert np.allclose(p, predict(fitted, r, case), rtol=1e-12, atol=1e-14)
                distributions += 1
            metrics = run.reuse.prior.old.reuse.metrics(test, pp, case)
            assert run.reuse.prior.old.reuse.helper.summary(metrics) == assessment['annual'][str(year)][case]
            if year == 2023:
                continue
            accumulated[case].extend(metrics)
            maps = {rule: {row['race_id']: row for row in purchases[case + '_' + rule]} for rule in ('P01', 'A')}
            for r, p in zip(test, pp, strict=True):
                choices = choose(p, r['prices'])
                for rule in ('P01', 'A'):
                    saved = maps[rule][r['race_id']]
                    selected = choices[rule]
                    assert saved['indices'] == selected and saved['stake_yen'] == len(selected) * 100
                    assert saved['hits'] == int(r['winner'] in selected) and saved['paid_yen'] == saved['hits'] * r['payout_yen']
                    settlements += 1
    assert accumulated == precision
    statistics(purchases, assessment['purchase'], True)
    for case in ('S10', 'M10'):
        ci = run.probability_ci(accumulated[case], accumulated['S0_direct'])
        assert ci == assessment['comparisons'][case]['loss_improvement_ci95']
        checks = {'loss_improvement_ci_positive': ci[0] > 0,
            'every_year_loss_better': all(assessment['annual'][str(y)][case]['logloss'] < assessment['annual'][str(y)]['S0_direct']['logloss'] for y in (2024, 2025, 2026)),
            'hits_at_least_direct': assessment['pooled'][case]['hit_rate'] >= assessment['pooled']['S0_direct']['hit_rate']}
        assert checks == assessment['comparisons'][case]['checks']
        assert assessment['comparisons'][case]['probability_promising'] == all(checks.values())
    captures = run.reuse.prior.readlines(run.reuse.prior.CAP / 'inputs.jsonl.gz')
    early = {r['race_id']: r for r in captures if r['timing'] == 't_minus_30m'}
    late = {r['race_id']: r for r in captures if r['timing'] == 't_minus_10m'}
    replay = run.read(folder / 'capture-replay.json')
    replay_count = 0
    for f in replay['accepted']:
        r = run.model.from_observations(early[f['race_id']], late[f['race_id']])
        for case, pp in f['probabilities'].items():
            fitted = joblib.load(folder / f'2026_{case}.joblib')
            assert np.allclose(pp, predict(fitted, r, case), rtol=1e-12, atol=1e-14)
            replay_count += 1
    result = {'status': 'passed', 'archive_inputs': checked_inputs, 'distributions': distributions,
              'purchase_settlements': settlements, 'capture_distributions': replay_count, 'new_models': 8,
              'unknown_test': False, 'verifier_sha256': run.sha(Path(__file__))}
    run.save(folder / 'independent-verification.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=run.ROOT / 'artifacts/jra_research/ten_minute_20261107')
    verify(parser.parse_args().output)
