"""概要: J23最終判定を公開特徴からの別式推論・全精算・開催日再抽出で独立照合する。
作成日: 2026-10-24
入力: j23_final_autumn_20261024の全予測、公開特徴、月別モデルと採否。
出力: independent-verification.json、calibration.json。成功0、不一致時は例外停止。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_j23_final_20261024.py
注意事項: SQL・HTTP・学習なし。予測元ファイルは変更せず新規検算だけを保存。
"""

from collections import defaultdict
import gzip
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
FOLDER = ROOT/'artifacts/jra_research/j23_final_autumn_20261024'


def read(path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text('utf-8'))


def sha(path):
    """実ファイルバイトのSHA256を返す。"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    """検算結果をUTF-8で排他保存する。"""
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def infer(model, row):
    """元learnerを呼ばず、公開12馬列から28ペア列とsoftmaxを再計算する。"""
    x = np.asarray(row['x'], dtype=np.float32)
    market, pl = np.asarray(row['market']), np.asarray(row['pl'])
    left, right = np.array(list(combinations(range(len(x)), 2))).T
    a, b = x[left], x[right]
    matrix = np.column_stack((np.log(market), (a+b)/2, np.abs(a-b)))
    gap = np.clip(np.log(pl/market), -10, 10)
    confidence = (x[left, 9]+x[right, 9])/2
    clock = (x[left, 0]+x[right, 0])/2
    matrix = np.column_stack((matrix, gap, gap*clock, gap*confidence))
    matrix -= market@matrix
    assert matrix.shape[1] == 28
    transformed = matrix.astype(np.float32)/model['scale'].astype(np.float32)
    logits = np.log(market)+transformed@model['coef']
    p = np.exp(logits-logits.max())
    return p/p.sum()


def main():
    """モデル・全予測・集計・主区間・採否を別処理で照合する。

    Raises:
        AssertionError: 保存値と別計算が一致しない場合。
        FileExistsError: 検算出力が既に存在する場合。
    Notes:
        SQL/HTTP/学習は行わず、固定パスの検算と校正診断ファイルだけを新規保存する。
        モデル式を独立に再計算する技術照合であり、試験期間の未知性を保証しない。
    """
    assert not (FOLDER/'failure.json').exists()
    result, protocol = read(FOLDER/'assessment.json'), read(FOLDER/'protocol.json')
    ledger = read(FOLDER/'compact-ledger.json')
    lookup = {(r['race_id'], r['policy']): r for r in ledger}
    assert len(lookup) == len(ledger)
    models, model_checks = {}, 0
    for path in sorted((FOLDER/'models').glob('*.json')):
        cell = read(path)
        assert cell['trained_through'] < cell['month']+'-01'
        assert len(cell['training_race_ids']) == cell['train_races']
        assert all('20200101' <= key[:8] < cell['month'].replace('-', '')+'01' for key in cell['training_race_ids'])
        model_path = ROOT/cell['model_path']
        assert sha(model_path) == cell['model_sha256']
        model = joblib.load(model_path)
        assert model['trained_through'] == cell['trained_through'] and model['train_races'] == cell['train_races']
        models[cell['month']] = model
        model_checks += 1
    assert model_checks == 15
    counts, checked, races, old_matches = defaultdict(int), 0, set(), 0
    old_lookup = {(r['race_key'], r['model']): r for r in read(ROOT/'artifacts/jra_research/j23_early_autumn_20261023/ledger.json')}
    edges = [0, .01, .02, .03, .05, .1, .2, .3, .5, 1.000000001]
    calibration = {k: [[0, 0., 0] for _ in range(9)] for k in ('all_pairs', 'top1', 'purchased')}
    distribution_details = {'top1': [], 'purchased': []}
    prediction_path = FOLDER/'predictions.jsonl.gz'
    prediction_sha = sha(prediction_path)
    with gzip.open(prediction_path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            assert row['race_id'] not in races
            races.add(row['race_id'])
            assert row['race_id'][8:10] in ('05', '06') and row['date'][5:7] in ('09', '10', '11')
            p, q, pl, prices = (np.asarray(row[k]) for k in ('probability', 'market', 'pl', 'prices'))
            assert len(p) == len(row['horses'])*(len(row['horses'])-1)//2
            assert len(row['horses']) >= 8 and np.all(p > 0) and abs(p.sum()-1) < 1e-9
            assert np.allclose(q, (1/prices)/(1/prices).sum(), rtol=0, atol=1e-12)
            assert np.allclose(p, infer(models[row['month']], row), rtol=0, atol=1e-12)
            eligible = [i for i in range(len(p)) if 4 <= prices[i] <= 80 and p[i] >= .015 and p[i]*prices[i] >= 1.05]
            chosen = min(eligible, key=lambda i: (-round(float(p[i]*prices[i]), 12), i)) if eligible else None
            assert chosen == row['chosen']
            policies = [('J23_original', chosen, p), ('J23_top1', int(np.argmax(p)), p),
                        ('M0_top1', int(np.argmax(q)), q), ('PL_top1', int(np.argmax(pl)), pl)]
            for policy, index, distribution in policies:
                actual = lookup[(row['race_id'], policy)]
                assert actual['index'] == index
                assert actual['hit'] == int(index == row['winner'])
                assert actual['payout'] == (row['payout_per_100']*6 if index == row['winner'] else 0)
                assert actual['p'] == (float(distribution[index]) if index is not None else None)
                assert abs(actual['loss']+math.log(float(distribution[row['winner']]))) < 1e-12
                assert abs(actual['brier']-float((distribution@distribution-2*distribution[row['winner']]+1)/len(distribution))) < 1e-12
                checked += 1
            if row['date'][:4] < '2024':
                old = old_lookup[(row['race_id'], 'J23')]
                assert old['chosen'] == chosen and old['winner'] == row['winner']
                assert abs(old['winning_probability']-p[row['winner']]) < 1e-12
                assert old['payout'] == lookup[(row['race_id'], 'J23_original')]['payout']
                old_matches += 1
            for population, indices in [('all_pairs', range(len(p))), ('top1', [int(np.argmax(p))]),
                                        ('purchased', [chosen] if chosen is not None else [])]:
                for i in indices:
                    band = next(j for j in range(9) if edges[j] <= p[i] < edges[j+1])
                    totals = calibration[population][band]
                    totals[0] += 1
                    totals[1] += p[i]
                    totals[2] += int(i == row['winner'])
                    if population != 'all_pairs':
                        distribution_details[population].append({'p': float(p[i]), 'odds': float(prices[i]),
                            'rank': int(np.sum(p > p[i])+1)})
            counts[row['month']] += 1
    assert checked == len(ledger) and old_matches == 805
    summary_checks = 0
    for scope, s in result['summaries'].items():
        values = [r for r in ledger if scope == 'all_2021_2025' or
                  (r['date'][:4] in ('2024', '2025') if scope == 'primary_2024_2025' else
                   r['race_id'][8:10] == {'tokyo': '05', 'nakayama': '06'}[scope] if scope in ('tokyo', 'nakayama') else
                   r['date'][:4] == scope)]
        for policy in ('J23_original', 'J23_top1', 'M0_top1', 'PL_top1'):
            rows = [r for r in values if r['policy'] == policy]
            selected = [r for r in rows if r['index'] is not None]
            actual = s[policy]
            assert actual['races'] == len(rows) and actual['selections'] == len(selected)
            assert actual['hits'] == sum(r['hit'] for r in selected)
            assert actual['payout_yen'] == sum(r['payout'] for r in selected)
            assert actual['stake_yen'] == len(selected)*600
            assert actual['profit_yen'] == actual['payout_yen']-actual['stake_yen']
            assert actual['roi'] == (actual['payout_yen']/actual['stake_yen'] if actual['stake_yen'] else None)
            assert actual['hit_rate'] == (sum(r['hit'] for r in selected)/len(selected) if selected else None)
            assert abs(actual['logloss']-math.fsum(r['loss'] for r in rows)/len(rows)) < 1e-12
            summary_checks += 1
    bootstrap_checks = 0
    for scope in ('primary_2024_2025', 'all_2021_2025'):
        daily = defaultdict(lambda: np.zeros(4))
        for r in ledger:
            if scope == 'primary_2024_2025' and r['date'][:4] not in ('2024', '2025'):
                continue
            a = daily[r['date']]
            if r['policy'] == 'J23_top1':
                a[0] += r['hit']; a[1] += 1
            elif r['policy'] == 'M0_top1':
                a[0] -= r['hit']
            elif r['policy'] == 'J23_original' and r['index'] is not None:
                a[2] += 600; a[3] += r['payout']
        a = np.array([daily[d] for d in sorted(daily)])
        rng, differences, rois = np.random.default_rng(345), [], []
        for _ in range(20000):
            total = a[rng.integers(0, len(a), len(a))].sum(axis=0)
            differences.append(total[0]/total[1])
            if total[2]:
                rois.append(total[3]/total[2])
        expected = result['summaries'][scope]['intervals']
        assert np.allclose(np.quantile(differences, [.025, .975]), expected['top1_minus_market_ci95'], rtol=0, atol=1e-12)
        assert np.allclose(np.quantile(rois, [.025, .975]), expected['original_roi_ci95'], rtol=0, atol=1e-12)
        bootstrap_checks += 2
    primary = result['summaries']['primary_2024_2025']
    gates = result['accuracy_gates']
    expected_gates = {'at_least_400_races': primary['J23_top1']['races'] >= 400,
                      'at_least_40_days': primary['intervals']['days'] >= 40,
                      'pooled_gain_at_least_2pp': primary['top1_minus_market'] >= .02,
                      'difference_ci_lower_above_zero': primary['intervals']['top1_minus_market_ci95'][0] > 0,
                      'positive_gain_both_years': all(result['summaries'][str(y)]['top1_minus_market'] > 0 for y in (2024, 2025)),
                      'logloss_improves_both_years': all(result['summaries'][str(y)]['J23_top1']['logloss'] < result['summaries'][str(y)]['M0_top1']['logloss'] for y in (2024, 2025))}
    assert gates == expected_gates and result['accuracy_research_candidate_passed'] == all(gates.values())
    full = result['summaries']['all_2021_2025']
    original = full['J23_original']
    expected_profit = {'at_least_100_bets': original['selections'] >= 100,
                       'at_least_30_days': original['selection_days'] >= 30,
                       'at_least_10_hits': original['hits'] >= 10,
                       'roi_at_least_105pct': original['roi'] >= 1.05,
                       'roi_ci_lower_above_100pct': full['intervals']['original_roi_ci95'][0] > 1,
                       'earlier_period_minimum_gate': read(ROOT/'artifacts/jra_research/j23_early_autumn_20261023/results.json')['J23']['all']['minimum_gate_passed']}
    assert result['profit_gates'] == expected_profit
    assert result['original_purchase_candidate_passed'] == all(expected_profit.values())
    for name, digest in {**protocol['source_sha256'], **read(FOLDER/'data-sha256.json')}.items():
        assert sha(ROOT/name) == digest
    assert sha(prediction_path) == prediction_sha
    details = {}
    for name, values in distribution_details.items():
        details[name] = {'n': len(values), 'mean_probability': float(np.mean([v['p'] for v in values])),
                         'median_odds': float(np.median([v['odds'] for v in values])),
                         'median_probability_rank': float(np.median([v['rank'] for v in values]))}
    save(FOLDER/'calibration.json', {'edges': edges, 'bands_count_expected_hits_actual_hits': calibration,
                                   'selected_distribution': details, 'is_diagnostic_not_threshold_selection': True})
    value = {'status': 'passed', 'models': model_checks, 'races': len(races), 'ledger_rows_checked': checked,
             'old_J23_measures_matched': old_matches, 'summary_checks': summary_checks,
             'independent_probability_formula_checks': len(races), 'independent_bootstrap_checks': bootstrap_checks,
             'future_teacher_rows': 0, 'fixed_gate_checks': 'passed', 'input_and_source_sha256_unchanged': True,
             'predictions_sha256': prediction_sha, 'production_adoption': False}
    save(FOLDER/'independent-verification.json', value)
    print(json.dumps(value))


if __name__ == '__main__':
    main()
