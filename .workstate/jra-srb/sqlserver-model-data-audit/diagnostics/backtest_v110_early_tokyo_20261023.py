"""概要: V110方式を月初以前だけで学習し、指定年の非夏東京を検証する（既定2021〜2023年）。
作成日: 2026-10-23
入力: 既定spec330、指定評価年までの保存v2の2020年以降43履歴/T30市場/公式精算、既存V110関数。
出力: 新規runのprotocol/coverage/除外/モデル/全確率/会計/集計。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/backtest_v110_early_tokyo_20261023.py --output artifacts/jra_research/v110_early_tokyo_20261023
注意事項: SQL/HTTP/外部取得/実購入なし。別wrapperでSPEC/評価年/月を指定できる。v1とv2の履歴意味差を明記し、結果による救済をしない。
"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'scripts'))
import jra_second_ten_model as model_code
from jra_ten_trials_model import pair_probability, pick_ticket
from evaluate_jra_o1o2_movement import payout_map
from jra_srb.jra_history_dataset import FEATURE_NAMES
from jra_srb.jra_research_contracts import ResearchError, timestamp

DATA = ROOT/'data/training/jra_o1o2_asof_v2/20261002-raw-v2-complete'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/330-V110の2021年から2023年東京の固定遡及検証.md'
EVALUATION_YEARS = (2021,2022,2023)
MONTHS = [f'{y}-{m:02d}' for y in EVALUATION_YEARS for m in range(1,13) if m not in (6,7,8)]
POLICY = {'group':'all','threshold':1.05}


def require(condition, reason):
    """不整合は固定理由を持つ例外にする。"""
    if not condition:
        raise ResearchError(reason)


def sha(path):
    """ファイルの実バイトSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """新規JSONをUTF-8/LF・非有限数値拒否で排他保存する。"""
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def isolated_probability(top3, record):
    """元V110で実際に使うtop3→馬連の既存2関数だけを呼ぶ。"""
    return pair_probability(model_code.choice(top3, record), record['pair']['indices'])


def load_records(output, end_year=2023):
    """2020〜指定末年の保存v2を元prepareで変換し、結果を教師/精算欄へ分離する。"""
    report_path=ROOT/'.workstate/jra-srb/jra-second-ten-nosummer-v1/report.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    for name,value in report['source_hashes'].items():
        require(sha(ROOT/'scripts'/name)==value,'v110_legacy_source_changed')
    final_path=report_path.parent/report['final_artifact']['file']
    require(sha(final_path)==report['final_artifact']['sha256'],'v110_equivalence_model_changed')
    suite=joblib.load(final_path)
    records,excluded,hashes,coverage,seen,probes=[],[],{}, {},set(),0
    for year in range(2020,end_year+1):
        path=DATA/str(year)/'races.jsonl.gz'
        manifest=json.loads((path.parent/'manifest.json').read_text(encoding='utf-8'))
        hashes[str(path.relative_to(ROOT))]=sha(path)
        require(hashes[str(path.relative_to(ROOT))]==manifest['files']['races.jsonl.gz']['sha256'],'v110_dataset_hash')
        counts=Counter()
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line in stream:
                raw=json.loads(line)
                key,day=raw['race_id'],raw['race_date']
                require(key not in seen,'v110_duplicate_race')
                seen.add(key)
                counts['stored']+=1
                if int(day[5:7]) in (6,7,8):
                    counts['excluded_summer']+=1
                    continue
                try:
                    require(str(year)==day[:4] and day.replace('-','')==key[:8],'v110_date_identity')
                    inp=raw['inputs']
                    require(inp['history_as_of']==day+'T00:00:00+09:00','v110_history_cutoff')
                    clean={'race_id':key,'race_date':day,'race':deepcopy(raw['race']),
                           'inputs':{'runners':deepcopy(inp['runners']),'history_as_of':inp['history_as_of'],
                                     'odds':{'T-30m':deepcopy(inp['odds']['T-30m'])}}}
                    for runner in clean['inputs']['runners']:
                        h=runner['history_features']
                        require(set(h)==set(FEATURE_NAMES) and all(np.isfinite(float(v)) for v in h.values()),
                                'v110_history_columns')
                    cutoff=timestamp(raw['race']['start_at'])-timedelta(minutes=30)
                    for market in clean['inputs']['odds']['T-30m'].values():
                        require(market is not None and timestamp(market['announced_at']) <= timestamp(market['cutoff']) == cutoff,
                                'v110_market_cutoff')
                    r=model_code.prepare(clean)
                    require(r['pair'] is not None,'v110_missing_pair_market')
                    require(r['enriched_names']==suite['enriched_feature_names'],'v110_feature_order')
                    ranks={str(k):int(v) for k,v in raw['result']['ranks_by_horse'].items()}
                    wins={k for k,v in ranks.items() if v==1}
                    win_payout=payout_map(raw['result']['win_payout_per_100_yen'],'win')
                    require(bool(wins) and wins==set(win_payout) and wins.issubset(r['keys']),'v110_win_label_roster')
                    require(all(k in r['keys'] for k,v in ranks.items() if v>0),'v110_rank_roster')
                    paid=payout_map(raw['result']['quinella_payout_per_100_yen'],'quinella')
                    paid={'-'.join(k):v for k,v in paid.items()}
                    q=r['pair']
                    require(bool(paid) and set(paid).issubset(q['keys']) and all(v>0 for v in paid.values()),'v110_pair_settlement')
                    if counts['accepted']==0:
                        old=model_code.score_suite(suite,r)['V110']['probability']
                        separated=isolated_probability(suite['top3'],r)
                        require(np.array_equal(old,separated),'v110_separation_not_equivalent')
                        mutated=deepcopy(raw)
                        mutated['result']={'bad':'ignored'}
                        mutated['inputs']['odds']['T-10m']={'bad':'ignored'}
                        changed=model_code.prepare(mutated)
                        require(np.array_equal(r['enriched'],changed['enriched']) and
                                np.array_equal(old,isolated_probability(suite['top3'],changed)), 'v110_result_dependency')
                        probes+=1
                    r['training_ranks']=np.asarray([ranks.get(k,0) for k in r['keys']],dtype=int)
                    q['target']=np.asarray([float(k in paid)/len(paid) for k in q['keys']])
                    q['payout']=np.asarray([paid.get(k,0) for k in q['keys']],dtype=int)
                    kept={k:r[k] for k in ('keys','market','enriched','enriched_names','training_ranks',
                                          'pair','race_id','race_date','course','surface','distance')}
                    records.append(kept)
                    counts['accepted']+=1
                except (ResearchError,KeyError,TypeError,ValueError) as error:
                    reason=error.reason if isinstance(error,ResearchError) else 'v110_input_structure'
                    if reason in ('v110_separation_not_equivalent', 'v110_result_dependency'):
                        raise
                    excluded.append({'race_id':key,'reason':reason})
                    counts['excluded_'+reason]+=1
        coverage[str(year)]=dict(counts)
        save(output/f'coverage-{year}.json',coverage[str(year)])
        print(json.dumps({'stage':'records','year':year,'counts':dict(counts)},ensure_ascii=False),flush=True)
    require(probes==end_year-2019,'v110_equivalence_probes_incomplete')
    records.sort(key=lambda r:(r['race_date'],r['race_id']))
    save(output/'excluded.json',excluded)
    save(output/'input-sha256.json',hashes)
    save(output/'formula-equivalence.json',{'status':'passed','probes':probes,
        'separated_V110_equals_original_score_suite':True,'result_and_T10_ignored':True,
        'future_trained_model_only_used_for_formula_probe_not_performance':True})
    return records,hashes


def summary(rows):
    """固定政策の会計・精度・高配当依存・日bootstrapを集計する。"""
    if not rows:
        return {'races':0,'roi':None}
    stake=sum(r['stake'] for r in rows)
    returned=sum(r['payout'] for r in rows)
    daily=defaultdict(lambda:[0,0])
    for r in rows:
        daily[r['race_date']][0]+=r['stake']
        daily[r['race_date']][1]+=r['payout']
    a=np.asarray([daily[k] for k in sorted(daily)],dtype=float)
    c=np.r_[0,np.cumsum(a[:,1]-a[:,0])]
    ci=None
    if stake:
        rng=np.random.default_rng(330)
        samples=[]
        for _ in range(20000):
            cost,paid=a[rng.integers(0,len(a),len(a))].sum(axis=0)
            if cost:samples.append(paid/cost)
        ci=np.quantile(samples,[.025,.975]).tolist()
    paid=sorted((r['payout'] for r in rows),reverse=True)
    value={'races':len(rows),'bets':sum(r['stake']>0 for r in rows),
        'buy_days':len({r['race_date'] for r in rows if r['stake']}),'hits':sum(r['payout']>0 for r in rows),
        'stake_yen':stake,'payout_yen':returned,'profit_yen':returned-stake,'roi':returned/stake if stake else None,
        'logloss':float(np.mean([r['loss'] for r in rows])),'brier':float(np.mean([r['brier'] for r in rows])),
        'roi_without_largest':(returned-paid[0])/stake if stake else None,
        'roi_without_top3':(returned-sum(paid[:3]))/stake if stake else None,'roi_ci95':ci,
        'max_drawdown_day_end_yen':int(np.max(np.maximum.accumulate(c)-c))}
    value['minimum_gate_passed']=bool(value['bets']>=100 and value['buy_days']>=30 and value['hits']>=10
        and value['roi'] is not None and value['roi']>=1.05 and ci and ci[0]>1)
    return value


def measure(r,probability,case,month):
    """元pick_ticketの最大1点を600円換算し、複数正解も元式で精算する。"""
    q=r['pair']
    require(np.isfinite(probability).all() and (probability>0).all() and abs(float(probability.sum())-1)<1e-9,
            'v110_probability_contract')
    score={'probability':probability,'projected_return':probability*q['price']}
    ticket=pick_ticket(q,score,'quinella',POLICY)
    index=ticket['index'] if ticket else None
    return {'race_id':r['race_id'],'race_date':r['race_date'],'month':month,'model':case,
        'loss':float(-q['target']@np.log(probability)), 'brier':float(np.mean((probability-q['target'])**2)),
        'pair_count':len(probability),'probability_sum':float(probability.sum()),
        'chosen':index,'ticket_probability':float(probability[index]) if index is not None else None,
        'ticket_odds':float(q['price'][index]) if index is not None else None,
        'stake':600 if ticket else 0,'payout':int(q['payout'][index])*6 if ticket else 0}


def run(output):
    """指定SPEC/評価年/月の過去限定学習・測定・元不変確認を行う。"""
    output.mkdir(parents=True,exist_ok=False)
    stage='protocol'
    try:
        paths=[ROOT/'scripts'/name for name in ('jra_second_ten_model.py','jra_ten_trials_model.py',
               'jra_v91_model.py','evaluate_jra_o1o2_movement.py')]
        save(output/'protocol.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),
            'spec_sha256':sha(SPEC),'months':MONTHS,'train_start':'2020-01-01','excluded_months':[6,7,8],
            'primary_scope':'tokyo_non_summer','secondary_scope':'tokyo_autumn','cases':['V110','PL','M0'],
            'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in paths},'policy':POLICY,
            'odds_inclusive':[3,100],'stake_yen':600,'max_fits':len(MONTHS),'is_unseen_validation':False})
        stage='load_records'
        records,hashes=load_records(output,end_year=max(EVALUATION_YEARS))
        (output/'folds').mkdir()
        ledger,skipped,fits=[],[],0
        with gzip.open(output/'predictions.jsonl.gz','wt',encoding='utf-8',newline='\n') as pred:
            for month in MONTHS:
                stage='fit_'+month
                train=[r for r in records if r['race_date']<month+'-01']
                test=[r for r in records if r['race_date'][:7]==month and r['course']=='tokyo']
                if not test:
                    skipped.append({'month':month,'reason':'no_eligible_tokyo_races'})
                    continue
                require(len(train)>=100 and max(r['race_date'] for r in train)<month+'-01','v110_temporal_split')
                with threadpool_limits(limits=1):
                    stages,weights=model_code.ranking_stages(train)
                    top3=model_code.fit_choice(stages,weights=weights)
                del stages,weights
                artifact={'case':'V110','top3':top3,'training_max_date':max(r['race_date'] for r in train),
                    'training_races':len(train),'feature_names':train[0]['enriched_names'],'excluded_months':[6,7,8]}
                path=output/'folds'/f'{month}.joblib'
                joblib.dump(artifact,path)
                restored=joblib.load(path)
                save(output/'folds'/f'{month}.json',{'month':month,'training_max_date':artifact['training_max_date'],
                    'train_races':len(train),'test_races':len(test),'model_sha256':sha(path),
                    'training_race_ids':[r['race_id'] for r in train]})
                for r in test:
                    with threadpool_limits(limits=1):
                        v=isolated_probability(restored['top3'],r)
                    scores={'V110':v,'PL':pair_probability(r['market'],r['pair']['indices']),'M0':r['pair']['market']}
                    for case,probability in scores.items():
                        row=measure(r,probability,case,month)
                        ledger.append(row)
                        pred.write(json.dumps({**row,'keys':r['pair']['keys'],'probability':probability.tolist(),
                            'price':r['pair']['price'].tolist(),'target':r['pair']['target'].tolist(),
                            'payout_per_100':r['pair']['payout'].tolist()},ensure_ascii=False,allow_nan=False)+'\n')
                fits+=1
                print(json.dumps({'stage':'evaluated','month':month,'train_races':len(train),'test_races':len(test)}),flush=True)
        stage='summaries'
        save(output/'ledger.json',ledger)
        results={}
        for case in ('V110','PL','M0'):
            rows=[r for r in ledger if r['model']==case]
            results[case]={'all':summary(rows),'years':{str(y):summary([r for r in rows if r['race_date'].startswith(str(y))]) for y in EVALUATION_YEARS},
                'autumn':summary([r for r in rows if int(r['race_date'][5:7]) in (9,10,11)])}
        for name,value in hashes.items():require(sha(ROOT/name)==value,'v110_data_changed')
        save(output/'skipped-months.json',skipped)
        save(output/'results.json',results)
        save(output/'verification.json',{'status':'passed','fits':fits,'ledger_rows':len(ledger),
             'source_unchanged':True,'future_training_rows':0,'production_adoption':False})
        print(json.dumps({'status':'complete','fits':fits,'results':results},ensure_ascii=False),flush=True)
    except Exception as error:
        save(output/'failure.json',{'status':'failed','stage':stage,
            'reason':error.reason if isinstance(error,ResearchError) else type(error).__name__})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
