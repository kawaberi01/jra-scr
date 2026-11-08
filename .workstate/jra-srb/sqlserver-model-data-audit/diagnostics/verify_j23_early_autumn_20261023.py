"""概要: 古い年代のJ23検証を別会計・確率式・日再標本化で独立照合する。
作成日: 2026-10-23
入力: backtest_j23_early_autumn_20261023.pyの新規成果物dir。
出力: independent-verification.json。成功0、矛盾時は例外で停止。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_j23_early_autumn_20261023.py --run artifacts/jra_research/j23_early_autumn_20261023
注意事項: 元成果物を変更せず、SQL/HTTP/学習をしない。独立未知試験を意味しない。
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[4]


def read(path):
    """UTF-8の保存JSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def verify(folder):
    """27セルの時間順・会計・確率と全体bootstrapを独立に照合する。"""
    protocol, results, ledger = read(folder/'protocol.json'), read(folder/'results.json'), read(folder/'ledger.json')
    assert not (folder/'failure.json').exists()
    assert len(protocol['months']) == 9
    expected, model_checks = [], 0
    for path in sorted((folder/'cells').glob('*.json')):
        cell = read(path)
        assert cell['trained_through'] < cell['month']+'-01'
        assert all(r['race_date'][:7] == cell['month'] and r['race_key'][8:10] in ('05', '06') for r in cell['rows'])
        model_path = path.with_suffix('.joblib')
        assert hashlib.sha256(model_path.read_bytes()).hexdigest() == cell['model_sha256']
        model = joblib.load(model_path)
        assert model['trained_through'] == cell['trained_through'] and model['train_races'] == cell['train_races']
        expected.extend(cell['rows'])
        model_checks += 1
    assert model_checks == 27
    assert sorted(expected, key=lambda r:(r['race_key'],r['model'])) == sorted(ledger,key=lambda r:(r['race_key'],r['model']))
    identities = defaultdict(set)
    for row in ledger:
        identities[row['race_key']].add(row['model'])
        assert row['stake'] in (0,600) and (row['chosen'] is not None) == bool(row['stake'])
        assert row['payout'] == (6*row['hr_payout_yen'] if row['chosen']==row['winner'] else 0)
        assert abs(row['loss']+math.log(row['winning_probability'])) < 1e-12
        assert abs(row['brier']-(row['squared_sum']-2*row['winning_probability']+1)/row['pair_count'])<1e-12
        assert row['minimum']>0 and abs(row['probability_sum']-1)<1e-9
    assert all(names=={'J23','R1','M0'} for names in identities.values())
    checks = 0
    for case in ('J23','R1','M0'):
        all_rows = [r for r in ledger if r['model']==case]
        groups = [('all',None,all_rows)]
        groups += [('years',str(y),[r for r in all_rows if r['race_date'].startswith(str(y))]) for y in (2021,2022,2023)]
        groups += [('venues',name,[r for r in all_rows if r['race_key'][8:10]==code]) for name,code in [('tokyo','05'),('nakayama','06')]]
        for axis,key,rows in groups:
            actual = results[case][axis] if key is None else results[case][axis][key]
            stake,payout = sum(r['stake'] for r in rows),sum(r['payout'] for r in rows)
            assert actual['stake']==stake and actual['payout']==payout and actual['profit_yen']==payout-stake
            assert actual['bets']==sum(bool(r['stake']) for r in rows)
            assert actual['hits']==sum(r['payout']>0 for r in rows)
            if stake:
                assert actual['roi']==payout/stake
                assert actual['roi_without_top3']==(payout-sum(sorted((r['payout'] for r in rows),reverse=True)[:3]))/stake
            checks += 1
    daily = defaultdict(lambda:[0,0])
    for row in ledger:
        if row['model']=='J23':
            daily[row['race_date']][0] += row['stake']
            daily[row['race_date']][1] += row['payout']
    a=np.asarray([daily[day] for day in sorted(daily)],dtype=float)
    rng=np.random.default_rng(325)
    draws=[]
    for _ in range(20000):
        picked=rng.integers(0,len(a),len(a))
        cost,paid=np.sum(a[picked],axis=0)
        if cost:draws.append(paid/cost)
    assert np.allclose(np.quantile(draws,[.025,.975]),results['J23']['all']['roi_ci95'],rtol=0,atol=1e-12)
    for relative,expected_hash in read(folder/'data-sha256.json').items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==expected_hash
    for relative,expected_hash in protocol['source_sha256'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==expected_hash
    value={'status':'passed','cells':model_checks,'ledger_rows':len(ledger),'unique_test_races':len(identities),
           'summary_checks':checks,'bootstrap_checks':1,'future_training_rows':0,'source_unchanged':True,
           'independent_unseen_trial':False,'production_adoption':False}
    with (folder/'independent-verification.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    verify(parser.parse_args().run)
