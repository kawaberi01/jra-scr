"""概要: 旧年代V110の学習日・分布・選択・精算・代表数値推論を独立照合する。
作成日: 2026-10-23
入力: 指定成果物と元保存v2入力。評価年は関数引数、既定2021〜2023年。
出力: independent-verification.json。正常0、矛盾時は例外停止。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_v110_early_tokyo_20261023.py --run artifacts/jra_research/v110_early_tokyo_20261023
注意事項: SQL/HTTP/学習なし。元モデルや測定結果は変更しない。
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
import jra_second_ten_model as original


def read(path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def verify(folder, evaluation_years=(2021,2022,2023)):
    """指定評価年の全予測の確率/会計と代表各月推論を別式で確認する。"""
    assert not (folder/'failure.json').exists()
    protocol=read(folder/'protocol.json')
    result=read(folder/'results.json')
    ledger=read(folder/'ledger.json')
    by_key={(r['race_id'],r['model']):r for r in ledger}
    assert len(by_key)==len(ledger)
    models={}
    for path in sorted((folder/'folds').glob('*.json')):
        fold=read(path)
        assert fold['training_max_date'] < fold['month']+'-01'
        assert len(fold['training_race_ids'])==fold['train_races']
        assert all(k[:8] < fold['month'].replace('-','')+'01' and int(k[4:6]) not in (6,7,8)
                   and k[:4]>='2020' for k in fold['training_race_ids'])
        model_path=path.with_suffix('.joblib')
        assert hashlib.sha256(model_path.read_bytes()).hexdigest()==fold['model_sha256']
        models[fold['month']]=joblib.load(model_path)
        assert models[fold['month']]['training_max_date']==fold['training_max_date']
    probes,identities,checked={},defaultdict(set),0
    with gzip.open(folder/'predictions.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            p,prices,target,paid=(np.asarray(row[k]) for k in ('probability','price','target','payout_per_100'))
            assert len(p)==len(prices)==len(target)==len(paid)==row['pair_count']
            assert abs(p.sum()-1)<1e-9 and (p>0).all() and abs(target.sum()-1)<1e-9
            assert np.array_equal(target>0,paid>0)
            assert row['race_id'][8:10]=='05' and int(row['race_date'][5:7]) not in (6,7,8)
            assert row['race_date'][:7]==row['month']
            expected=np.flatnonzero((prices>=3)&(prices<=100)&(p*prices>=1.05))
            chosen=int(expected[np.argmax((p*prices)[expected])]) if len(expected) else None
            assert chosen==row['chosen']
            assert row['stake']==(600 if chosen is not None else 0)
            assert row['payout']==(int(paid[chosen])*6 if chosen is not None else 0)
            assert abs(row['loss']-float(-target@np.log(p)))<1e-12
            assert abs(row['brier']-float(np.mean((p-target)**2)))<1e-12
            if row['model']=='M0':
                market=1/prices
                market/=market.sum()
                assert np.allclose(market,p,rtol=0,atol=1e-12)
            if row['model']=='V110' and row['month'] not in probes:
                probes[row['month']]=row
            assert {k:v for k,v in row.items() if k in by_key[(row['race_id'],row['model'])]}==by_key[(row['race_id'],row['model'])]
            identities[row['race_id']].add(row['model'])
            checked+=1
    assert checked==len(ledger) and all(v=={'V110','PL','M0'} for v in identities.values())
    summary_checks=0
    for case in ('V110','PL','M0'):
        all_rows=[r for r in ledger if r['model']==case]
        groups=[(result[case]['all'],all_rows),(result[case]['autumn'],[r for r in all_rows if int(r['race_date'][5:7]) in (9,10,11)])]
        groups += [(result[case]['years'][str(y)],[r for r in all_rows if r['race_date'].startswith(str(y))]) for y in evaluation_years]
        for actual,rows in groups:
            stake=sum(r['stake'] for r in rows)
            returned=sum(r['payout'] for r in rows)
            assert actual['stake_yen']==stake and actual['payout_yen']==returned
            assert actual['profit_yen']==returned-stake
            assert actual['bets']==sum(r['stake']>0 for r in rows)
            assert actual['hits']==sum(r['payout']>0 for r in rows)
            if stake:
                assert actual['roi']==returned/stake
                assert actual['roi_without_top3']==(returned-sum(sorted((r['payout'] for r in rows),reverse=True)[:3]))/stake
            summary_checks+=1
    ids={v['race_id']:month for month,v in probes.items()}
    formula_checks=0
    for year in evaluation_years:
        path=ROOT/f'data/training/jra_o1o2_asof_v2/20261002-raw-v2-complete/{year}/races.jsonl.gz'
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line in stream:
                value=json.loads(line)
                if value['race_id'] not in ids:continue
                month=ids[value['race_id']]
                r=original.prepare(value)
                model=models[month]['top3']
                z=np.log(r['market'])+(r['enriched']/model['scale'])@model['coef']
                strength=np.exp(z-z.max())
                strength/=strength.sum()
                q=np.asarray([strength[i]*strength[j]*(1/max(1-strength[i],1e-12)+1/max(1-strength[j],1e-12))
                              for i,j in r['pair']['indices']])
                q=np.maximum(q,1e-12)
                q/=q.sum()
                assert np.allclose(q,probes[month]['probability'],rtol=0,atol=1e-12)
                formula_checks+=1
    assert formula_checks==len(models)
    rows=[r for r in ledger if r['model']=='V110']
    daily=defaultdict(lambda:[0,0])
    for row in rows:
        daily[row['race_date']][0]+=row['stake']
        daily[row['race_date']][1]+=row['payout']
    a=np.asarray([daily[d] for d in sorted(daily)],dtype=float)
    rng=np.random.default_rng(330)
    draws=[]
    for _ in range(20000):
        cost,paid=a[rng.integers(0,len(a),len(a))].sum(axis=0)
        if cost:draws.append(paid/cost)
    assert np.allclose(np.quantile(draws,[.025,.975]),result['V110']['all']['roi_ci95'],rtol=0,atol=1e-12)
    for path,value in read(folder/'input-sha256.json').items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==value
    for path,value in protocol['source_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==value
    verification={'status':'passed','folds':len(models),'ledger_rows':len(ledger),'test_races':len(identities),
        'summary_checks':summary_checks,'numeric_formula_checks':formula_checks,'bootstrap_checks':1,
        'future_training_rows':0,'input_and_source_unchanged':True,'is_unseen_validation':False,'production_adoption':False}
    with (folder/'independent-verification.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(verification,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps(verification,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    verify(parser.parse_args().run)
