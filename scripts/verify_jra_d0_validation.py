"""概要: D0部品除去の全分布と実用監査の全公式精算を独立式で検算する。
作成日: 2026-10-25
入力: --run 研究run、--kind ablation/usability、元D0と保存カード。
出力: independent-verification.json。不一致は例外で停止。
実行例: uv run --frozen --extra ml python scripts/verify_jra_d0_validation.py --run artifacts/jra_research/d0_ablation_20261025 --kind ablation
注意事項: 新fit/SQL/HTTP/実購入なし。既知過去を未知試験と扱わない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import defaultdict
from datetime import datetime
import gzip
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_quality_chimera as shared
from verify_jra_attribute_chimera import independent_predict
from verify_jra_course_class_chimera import metrics_check

ROOT, REFERENCE = shared.ROOT, shared.REFERENCE
read, save, sha, helper = shared.read, shared.save, shared.sha, shared.helper
ORDER = ('clock', 'opponent', 'aptitude', 'rotation')


def baseline_inputs(folder):
    """元datasetと保存分布のSHAを確認し、同一評価ロスターを返す。"""
    m = read(folder/'input-manifest.json')
    assert sha(ROOT/m['dataset']) == m['dataset_sha256']
    assert all(sha(ROOT/p) == v for p, v in m['baseline_sha256'].items())
    data = joblib.load(ROOT/m['dataset'])
    baseline, tests = {}, {}
    for year in (2023, 2024, 2025, 2026):
        prefix = '2026_selected' if year == 2026 else f'{year}_D0'
        cell = read(REFERENCE/(prefix+'.json'))
        pp = joblib.load(REFERENCE/(prefix+'_predictions.joblib'))
        test = data['later'] if year == 2026 else [r for r in data['records'] if r['race_date'].startswith(str(year))]
        assert cell['test_ids'] == [r['race_id'] for r in test]
        tests[year] = test
        baseline.update(zip(cell['test_ids'], pp, strict=True))
    return data['records'], tests, baseline


def grouped(rows, by_id):
    """保存された行から固定条件の全群を再構成する。"""
    groups = defaultdict(list)
    for row in rows:
        r = by_id[row['race_id']]
        band = sum(int(r['distance']) > edge for edge in (1400, 1800, 2200, 2600))
        prefix = str(r['course'])+':'+str(r['surface'])
        for key in ('cs:'+prefix, 'csd:'+prefix+':'+str(band), 'class:'+str(r['condition'])):
            groups[key].append(row)
    return {k: helper.summary(v) for k, v in sorted(groups.items())}


def verify_ablation(folder, manifest):
    """除去列・全確率・教師期間・選択・集計・CIを本体推論なしで再計算する。"""
    records, tests, baseline = baseline_inputs(folder)
    by_id = {r['race_id']: r for r in records+tests[2026]}
    excluded = {'clock': [2,3,4,17,18,19,32], 'opponent': [5,6,20,21],
        'aptitude': [7,8,9,10,22,23,24,25], 'rotation': [11,12,13,14,15,16,26,27,28,29,30,31,33]}
    rows_by_year, count = {}, 0
    for year, test in tests.items():
        values = {}
        for label in ('D0', 'market'):
            values[label] = []
            for r in test:
                p = baseline[r['race_id']] if label == 'D0' else r['market']
                y = r['winner']
                values[label].append({k: r[k] for k in ('race_id','race_date','course','surface')}|
                    {'label': label if label == 'D0' else 'M0', 'distance_band': sum(int(r['distance']) > e for e in (1400,1800,2200,2600)),
                     'season': (int(r['race_date'][5:7])%12)//3, 'loss': float(-np.log(p[y])),
                     'hit': int(np.argmax(p) == y), 'brier': float((p@p-2*p[y]+1)/len(p))})
        train = [r for r in records if r['race_date'] < f'{year}-01-01']
        for block in ORDER:
            prefix = f'{year}_{block}'
            cell = read(folder/(prefix+'.json'))
            model_path = folder/(prefix+'.joblib')
            assert sha(model_path) == manifest['model_sha256'][model_path.name] == cell['model_sha256']
            fitted = joblib.load(model_path)
            assert fitted['omitted'] == block and fitted['omitted_columns'] == excluded[block]
            assert fitted['ablation_protocol'] == 'spec405-D0-retrained-ablation-v1'
            assert np.count_nonzero(fitted['coef'][:, excluded[block]]) == 0
            assert cell['train_ids'] == [r['race_id'] for r in train] and cell['test_ids'] == [r['race_id'] for r in test]
            assert fitted['train_races'] == len(train) and fitted['trained_from'] == min(r['race_date'] for r in train)
            assert fitted['trained_through'] == max(r['race_date'] for r in train) < min(r['race_date'] for r in test)
            pp = joblib.load(folder/(prefix+'_predictions.joblib'))
            for r, p, row in zip(test, pp, cell['rows'], strict=True):
                np.testing.assert_allclose(p, independent_predict(fitted, r), rtol=1e-12, atol=1e-14)
                metrics_check(r, p, row)
                count += 1
            assert helper.summary(cell['rows']) == cell['summary']
            values[block] = cell['rows']
        rows_by_year[year] = values
    assessment, selection = read(folder/'assessment.json'), read(folder/'selection.json')
    annual = {str(y): {k: helper.summary(v) for k, v in vv.items()} for y, vv in rows_by_year.items()}
    assert annual == assessment['annual'] and annual['2023'] == selection['development']
    scores, d0 = annual['2023'], annual['2023']['D0']
    eligible = [k for k in ORDER if scores[k]['logloss'] < d0['logloss']-1e-8 and scores[k]['hit_rate'] >= d0['hit_rate']]
    choice = min(eligible, key=lambda k: (scores[k]['logloss'], ORDER.index(k))) if eligible else 'D0'
    assert choice == selection['chosen'] == assessment['chosen'] and eligible == selection['eligible']
    pooled = {k: [r for y in (2024,2025,2026) for r in rows_by_year[y][k]] for k in (*ORDER,'D0','market')}
    assert assessment['pooled'] == {k: helper.summary(v) for k, v in pooled.items()}
    assert assessment['groups'] == {k: grouped(v, by_id) for k, v in pooled.items()}
    for block in ORDER:
        a, b = helper.summary(pooled[block]), helper.summary(pooled['D0'])
        ci = helper.comparison_ci(pooled[block], pooled['D0'])
        checks = {'selected_in_development': choice == block, 'pooled_loss_better': a['logloss'] < b['logloss'],
            'loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
            'market_loss_better_each_year': all(annual[str(y)][block]['logloss'] < annual[str(y)]['market']['logloss'] for y in (2024,2025,2026)),
            'hit_rate_not_worse': a['hit_rate'] >= b['hit_rate']}
        assert assessment['comparisons'][block] == {'checks': checks, 'vs_D0_ci': ci, 'promising_research_candidate': all(checks.values())}
    return {'models': 16, 'independent_distributions': count, 'all_groups_verified': True,
        'selection_and_gates_verified': True, 'future_training_rows': 0}


def settlement_summary(rows):
    """主監査の集計関数を呼ばず、全精算と回収率を円の足し算で求める。"""
    n, paid, hits = len(rows), sum(r['payout_yen'] for r in rows), sum(r['hit'] for r in rows)
    top = sorted((r['payout_yen'] for r in rows if r['hit']), reverse=True)
    balance, peak, dd = 0, 0, 0
    for row in sorted(rows, key=lambda r: r['race_id']):
        balance += row['payout_yen']-100
        peak = max(peak, balance)
        dd = max(dd, peak-balance)
    return {'races': n, 'hits': hits, 'stake_yen': n*100, 'payout_yen': paid, 'net_yen': paid-n*100,
        'roi': paid/(n*100), 'hit_rate': hits/n, 'max_drawdown_yen': dd,
        'largest_hit_payout_yen': top[0] if top else 0,
        'net_without_largest_hit_yen': paid-sum(top[:1])-100*(n-min(1,len(top))),
        'net_without_top5_hits_yen': paid-sum(top[:5])-100*(n-min(5,len(top)))}


def verify_usability(folder, manifest):
    """元公式結果から全精算行・区間・入力採否と前向き実績0を再照合する。"""
    records, tests, baseline = baseline_inputs(folder)
    by_id = {r['race_id']: r for y in (2024,2025,2026) for r in tests[y]}
    outcomes, official = read(folder/'official-outcomes.json'), {}
    for relative, digest in manifest['card_sha256'].items():
        assert sha(ROOT/relative) == digest
        with gzip.open(ROOT/relative, 'rt', encoding='utf-8') as stream:
            for line in stream:
                source = json.loads(line)
                key = source['race_id']
                if key not in by_id:
                    continue
                r, result = by_id[key], source['result']
                winning = sorted(int(h) for h, rank in result['ranks_by_horse'].items() if rank in (1,2))
                pair = list(map(int, list(combinations(r['horses'],2))[r['winner']]))
                assert winning == pair and len(result['quinella_payout_per_100_yen']) == 1
                payout = result['quinella_payout_per_100_yen'][0]
                assert pair == sorted([int(payout['horse_no_1']),int(payout['horse_no_2'])])
                official[key] = int(payout['payout'])
                assert outcomes[key] == {'winner_pair': pair, 'payout_per_100_yen': official[key],
                    'source_dataset_payout_present': 'payout_yen' in r}
                if 'payout_yen' in r:
                    assert r['payout_yen'] == official[key]
    assert set(official) == set(by_id) == set(outcomes)
    probabilities = {'D0': baseline, 'market': {k:r['market'] for k,r in by_id.items()}, 'BC': {}}
    bcroot = ROOT/'artifacts/jra_research/class_D0_20261025'
    assert all(sha(ROOT/p) == h for p,h in manifest['bc_predictions_sha256'].items())
    for year in (2024,2025,2026):
        c = read(bcroot/f'{year}_BC.json')
        probabilities['BC'].update(zip(c['test_ids'], joblib.load(bcroot/f'{year}_BC_predictions.joblib'), strict=True))
    tickets, returns = read(folder/'tickets.json'), read(folder/'returns.json')
    for label, rows in tickets.items():
        assert [r['race_id'] for r in rows] == [r['race_id'] for y in (2024,2025,2026) for r in tests[y]]
        grouped_rows, daily = defaultdict(list), defaultdict(lambda:[0,0])
        for row in rows:
            key = row['race_id']
            r, p = by_id[key], probabilities[label][key]
            chosen = int(np.argmax(p))
            hit = int(chosen == r['winner'])
            assert row['pair_index'] == chosen and row['top_probability'] == float(p[chosen])
            assert row['hit'] == hit and row['payout_yen'] == (official[key] if hit else 0)
            assert row['race_date'] == r['race_date'] and row['course'] == int(r['course']) and row['surface'] == int(r['surface'])
            band = sum(int(r['distance']) > e for e in (1400,1800,2200,2600))
            assert row['distance_band'] == band
            for group in ('year:'+r['race_date'][:4], 'course:'+str(r['course']), 'sd:'+str(r['surface'])+':'+str(band)):
                grouped_rows[group].append(row)
            daily[r['race_date']][0] += row['payout_yen']
            daily[r['race_date']][1] += 100
        assert settlement_summary(rows) == returns[label]['all']
        assert {k:settlement_summary(v) for k,v in grouped_rows.items()} == returns[label]['groups']
        days = sorted(daily)
        rng = np.random.default_rng(410)
        draws = rng.integers(0,len(days),size=(2000,len(days)))
        pairs = np.array([daily[k] for k in days],dtype=np.int64)
        totals = np.sum(pairs[draws],axis=1)
        assert returns[label]['roi_ci'] == {'days':len(days),'draws':2000,
            'roi_ci95':np.quantile(totals[:,0]/totals[:,1],[.025,.975]).tolist()}
    audit = read(folder/'input-audit.json')
    assert all(sha(ROOT/p) == h for p,h in audit['source_sha256'].items())
    scoutpath = next(p for p in audit['source_sha256'] if p.endswith('scout-final.json'))
    scout = read(ROOT/scoutpath)
    assert audit['inventory'] == len(scout['entries']) and audit['reference_analyzed'] == sum(r['status']=='analyzed' for r in scout['entries'])
    assert audit['strict_eligible'] == 0 and all(not e['strict_prospective_eligible'] for e in audit['entries'])
    d0, d = returns['D0'], read(folder/'decision.json')
    checks = {'prospective_sample_sufficient':False,'predictions_and_rule_fixed_before_results':False,
        'asof_and_history_verified':False,'roi_ci_lower_above_one':d0['roi_ci']['roi_ci95'][0]>1,
        'annual_profit_robust':all(v['net_yen']>0 for k,v in d0['groups'].items() if k.startswith('year:')),
        'not_single_hit_dependent':d0['all']['net_without_largest_hit_yen']>0}
    assert d['checks'] == checks and not d['purchase_adopted'] and d['decision'] == 'do_not_adopt_currently'
    protocol = read(folder/'prospective-protocol.json')
    assert protocol['accepted'] == 0 and not protocol['performance_trial_started']
    assert (datetime.fromisoformat(protocol['end_at'])-datetime.fromisoformat(protocol['fixed_at'])).days == 180
    assert protocol['minimum_races'] == 1000 and protocol['minimum_days'] == 40
    return {'official_payout_races':len(official),'settled_tickets':sum(map(len,tickets.values())),
        'all_ROI_and_intervals_verified':True,'current_decision_verified':True,'prospective_eligible':0}


def verify(folder, kind):
    """ソース/全出力SHAを確認して種別に応じた独立検算を実行する。"""
    manifest = read(folder/'manifest.json')
    assert manifest['status'] == 'complete' and not (folder/'failure.json').exists()
    assert all(sha(ROOT/p) == h for p,h in manifest['source_sha256'].items())
    if kind == 'usability':
        assert all(sha(folder/p) == h for p,h in manifest['outputs_sha256'].items())
        detail = verify_usability(folder,manifest)
    else:
        assert sha(folder/'assessment.json') == manifest['assessment_sha256']
        detail = verify_ablation(folder,manifest)
    output = {'status':'passed','kind':kind,**detail,'unknown_test':False,'verifier_sha256':sha(Path(__file__))}
    save(folder/'independent-verification.json',output)
    print(json.dumps(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--kind',choices=('ablation','usability'),required=True)
    args = parser.parse_args()
    verify(args.run,args.kind)
