"""概要: 固定10案のT-30研究と、SQL固定版による過去内容の純変換を行う。
作成日: 不明
入力: 旧研究の固定JSONL（build_rowsのみ）、研究専用SQL履歴接続。
出力: 研究成果物、メモリ内の履歴・内容特徴。
実行例: uv run --extra ml python scripts/run_jra_tipster_history.py
注意事項: load_historyはSQLのみ。旧main/build_rowsは旧JSONL入力のため新研究では直接実行しない。
"""
from __future__ import annotations
from bisect import bisect_left
from collections import defaultdict, Counter
from datetime import date
from itertools import combinations
from pathlib import Path
import json
import math
import re
import sys
import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from evaluate_jra_o1o2_movement import HISTORY_KEYS, history_features, market, payout_map, read_races, sha256, split_for

COURSES = ['nakayama','kyoto','kokura','tokyo','hanshin','chukyo','fukushima','niigata','hakodate','sapporo']
JAPANESE = dict(zip(['中山','京都','小倉','東京','阪神','中京','福島','新潟','函館','札幌'],COURSES,strict=True))
CONTENT_NAMES = ['observed_past_runs','latest_observed_age','latest_strength','best_strength',
                 'mean_strength','latest_closing_strength','mean_closing_strength',
                 'latest_position_gain','mean_position_gain','latest_corner_ratio',
                 'latest_pace_delta','latest_adverse_pace_proxy','latest_strength_drop']
CONDITION_NAMES = ['distance','surface_dirt','season_sin','season_cos',*COURSES,
                   'course_form_delta','distance_form_delta','surface_form_delta',
                   'course_history_size','distance_history_size','surface_history_size',
                   'distance_change','same_surface','same_course','front_density',
                   'front_density_x_last_position','restored_best_conditions',
                   'drop_x_restoration']

def number(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (ValueError,TypeError):
        return None

def identity(name, sex_age, race_date):
    match=re.fullmatch(r'([牡牝セ騸])\s*(\d+)',str(sex_age or ''))
    if not match or not name:
        return None
    return (name,int(race_date[:4])-int(match[2]),'F' if match[1]=='牝' else 'M')

def average(items, key):
    vals=[x[key] for x in items if x[key] is not None]
    return float(np.mean(vals)) if vals else np.nan

def load_history(*, sql_provenance=None):
    """SQL固定版だけから履歴を読み、旧来の内容特徴・日付索引へ変換する。

    Notes:
        対象日より前かどうかの選別は呼出し側のbisect_leftで行う。
        馬名・推定生年・性別の旧対応を維持し、完全な馬ID同定とは扱わない。
    """
    from jra_srb.jra_research_tipster import read_tipster_history
    raw,wide,source_audit=read_tipster_history(provenance=sql_provenance)
    grouped=defaultdict(list)
    for item in raw:
        rank=number(item['rank'])
        if rank and rank>=1:
            item['rank']=rank
            grouped[item['netkeiba_race_id']].append(item)
    histories=defaultdict(list)
    audit=Counter(source_audit)
    for items in grouped.values():
        n=len(items)
        closings=sorted(x for item in items if (x:=number(item['final_3f'])) is not None)
        for item in items:
            ident=identity(item['horse_name'],item['sex_age'],item['race_date'])
            if ident is None:
                audit['history_identity_unresolved']+=1
                continue
            distance=int(''.join(re.findall(r'\d',str(item['distance']))) or 0)
            final3f=number(item['final_3f'])
            position=re.findall(r'\d+',str(item['corner_order'] or ''))
            corner=int(position[-1])/n if position and 1<=int(position[-1])<=n else None
            pace=None
            try:
                laps=[float(x) for x in json.loads(item['race_laps_json'] or '[]')]
                # Partial first sectors and malformed lengths must not mimic fast pace.
                if distance%200==0 and len(laps)==distance//200 and len(laps)>=6 and all(8<x<20 for x in laps):
                    pace=float(np.mean(laps[:3])-np.mean(laps[-3:]))
            except (ValueError,TypeError):
                pass
            strength=1-(item['rank']-1)/max(n-1,1)
            histories[ident].append(dict(race_date=item['race_date'],
                ordinal=date.fromisoformat(item['race_date']).toordinal(),course=JAPANESE[item['course']],
                surface='turf' if item['surface']=='芝' else 'dirt',distance=distance,
                strength=strength,closing=1-closings.index(final3f)/max(len(closings)-1,1) if final3f is not None else None,
                gain=corner-item['rank']/n if corner is not None else None,corner=corner,pace=pace))
            audit['history_records']+=1
    for items in histories.values():
        items.sort(key=lambda x:x['ordinal'])
    indices={key:[x['ordinal'] for x in items] for key,items in histories.items()}
    return histories,indices,wide,audit

def build_rows(*, races=None, history_bundle=None, source_hashes=None, split_selector=None):
    """明示SQL入力または旧研究入力から、同じ純計算で馬別行を作る。

    Args:
        races: SQLから組み立てたメモリ内レース。指定時は旧JSONLを開かない。
        history_bundle: SQL内容履歴・日付索引・払戻・件数監査。
        source_hashes: SQL入力の来歴digest。races指定時は必須。
        split_selector: 新研究で事前固定した日付分割。省略時は旧研究の分割。
    Notes:
        引数なしは旧研究の再現用。新研究の入口では必ずSQL入力を明示する。
    """
    if races is not None and (history_bundle is None or source_hashes is None):
        raise ValueError('SQL input provenance required')
    histories,indices,wide,audit=history_bundle if history_bundle is not None else load_history()
    rows=[]
    race_meta={}
    maximum_past_date=None
    hashes=source_hashes if races is not None else {str(ROOT/'data/training/jra_o1o2_asof_v1'/str(y)/'races.jsonl.gz'):
            sha256(ROOT/'data/training/jra_o1o2_asof_v1'/str(y)/'races.jsonl.gz') for y in [2024,2025,2026]}
    for race in races if races is not None else read_races(ROOT/'data/training/jra_o1o2_asof_v1'):
        d=race['race_date']
        split=split_selector(d) if split_selector else split_for(d)
        if split is None and split_selector is None:
            split='later' if d>='2026-07-01' else None
        audit['dataset_races']+=1
        if split is None:
            continue
        win=market(race['inputs']['odds']['T-30m']['win'],'win')
        pair=market(race['inputs']['odds']['T-30m'].get('quinella'),'quinella')
        runners={str(x['horse_no']):x for x in race['inputs']['runners']}
        if len(win)<8 or any(x['history_features'].get('is_obstacle') for x in runners.values()):
            audit[split+'_excluded_small_or_obstacle']+=1
            continue
        total=sum(1/x for x in win.values())
        pair_total=sum(1/x for x in pair.values())
        marg=defaultdict(float)
        for (left,right),price in pair.items():
            marg[left]+=1/price/(2*pair_total)
            marg[right]+=1/price/(2*pair_total)
        ordinal=date.fromisoformat(d).toordinal()
        pasts={}
        for key,runner in runners.items():
            ident=identity(runner.get('horse_name'),runner.get('sex_age'),d)
            stop=bisect_left(indices.get(ident,[]),ordinal)
            past=[x for x in histories.get(ident,[])[:stop][-3:] if ordinal-x['ordinal']<=365]
            assert all(x['race_date']<d for x in past)
            pasts[key]=past
            for x in past:
                maximum_past_date=max(maximum_past_date or x['race_date'],x['race_date'])
        front_density=sum(bool(x and x[-1]['corner'] is not None and x[-1]['corner']<=.3) for k,x in pasts.items() if k in win)/len(win)
        current=[]
        for key,price in win.items():
            runner=runners.get(key)
            if runner is None:
                audit['odds_runner_unmatched']+=1
                continue
            h=runner['history_features']
            past=pasts[key]
            last=past[-1] if past else None
            best=max(past,key=lambda x:x['strength']) if past else None
            strength_drop=best['strength']-last['strength'] if last else 0.0
            distance=int(race['race']['distance'] or 0)
            surface=race['race']['surface']
            course=race['race']['course']
            restore=bool(last and best and strength_drop>=.15 and
                best['surface']==surface and abs(best['distance']-distance)<=200 and
                (last['surface']!=surface or abs(last['distance']-distance)>200))
            get=lambda field: last[field] if last and last[field] is not None else np.nan
            content=[len(past)/3,(ordinal-last['ordinal'])/365 if last else np.nan,
                get('strength'),best['strength'] if best else np.nan,average(past,'strength'),
                get('closing'),average(past,'closing'),get('gain'),average(past,'gain'),get('corner'),
                get('pace'),max(0,-last['pace']*(.5-last['corner'])) if last and last['pace'] is not None and last['corner'] is not None else np.nan,
                strength_drop if last else np.nan]
            month=int(d[5:7])
            condition=[distance/4000,int(surface=='dirt'),math.sin(2*math.pi*month/12),math.cos(2*math.pi*month/12),
                *[int(course==x) for x in COURSES],
                *[float(h.get(f'horse_{x}_top3_rate',.25))-float(h['horse_top3_rate']) for x in ['course','distance','surface']],
                *[float(h.get(f'horse_{x}_log_starts',0)) for x in ['course','distance','surface']],
                (distance-last['distance'])/2000 if last else np.nan,
                int(last['surface']==surface) if last else np.nan,int(last['course']==course) if last else np.nan,
                front_density,front_density*(.5-last['corner']) if last and last['corner'] is not None else np.nan,
                int(restore),strength_drop*restore]
            assert len(content)==len(CONTENT_NAMES) and len(condition)==len(CONDITION_NAMES)
            pwin=(1/price)/total
            basic=[math.log(price),pwin,*history_features(runner)]
            cross=[*basic,math.log(marg[key]/pwin) if marg[key]>0 else 0.0]
            rank=number(race['result']['ranks_by_horse'].get(key))
            if rank is None:
                raise ValueError('Missing label; do not silently shrink field')
            current.append(dict(race_id=race['race_id'],race_date=d,split=split,key=key,price=price,
                market_probability=pwin,basic=basic,cross=cross,content=content,condition=condition,
                top3=int(rank<=3),rank=int(rank),past_consistency=np.mean([x['strength']>=.8 for x in past]) if past else .25,
                restore=restore,strength_drop=strength_drop,has_history=bool(h.get('horse_has_history')),
                newcomer=bool(h.get('is_newcomer')),past_runs=len(past)))
            audit[split+'_runner_rows']+=1
            audit[split+'_with_recent_observed_history']+=int(bool(past))
            audit[split+'_with_latest_corner']+=int(last is not None and last['corner'] is not None)
            audit[split+'_with_latest_pace']+=int(last is not None and last['pace'] is not None)
        if len(current)!=len(win):
            raise ValueError('Incomplete runner join')
        rid=race['race_id']
        settle=wide.get((d,race['race']['course'],int(race['race']['race_no'])),{})
        if len(settle)<3:
            audit[split+'_wide_settlement_unavailable']+=1
            continue
        invalid=False
        for paid_pair in settle:
            ranks=race['result']['ranks_by_horse']
            if any(number(ranks.get(k)) is None or number(ranks[k])>3 for k in paid_pair):
                invalid=True
        if invalid:
            audit[split+'_wide_settlement_rank_conflict']+=1
            continue
        # Predictable inputs and settlement data remain separate.
        rows.extend(current)
        race_meta[rid]=dict(race_date=d,split=split,course=course,surface=surface,distance=distance,
            summer=6<=int(d[5:7])<=8,newcomer=any(x['newcomer'] for x in current),
            quinella=pair,quinella_payout=payout_map(race['result'].get('quinella_payout_per_100_yen',[]),'quinella'),wide_payout=settle)
        audit[split+'_eligible_races']+=1
    return rows,race_meta,audit,hashes,maximum_past_date

def matrix(rows,model):
    return np.asarray([r['cross']+(r['content'] if model in ['content','full'] else [])+
        (r['condition'] if model in ['condition','full'] else []) for r in rows],dtype=float)

def summarize(tickets,kind):
    selected=[t for t in tickets if t[kind+'_stake']]
    stake=sum(x[kind+'_stake'] for x in selected)
    returned=sum(x[kind+'_return'] for x in selected)
    biggest=max((x[kind+'_return'] for x in selected),default=0)
    worst=0
    peak=0
    balance=0
    daily=defaultdict(int)
    for x in selected:
        daily[x['race_date']]+=x[kind+'_return']-x[kind+'_stake']
    for day in sorted(daily):
        balance+=daily[day]
        peak=max(peak,balance)
        worst=max(worst,peak-balance)
    return dict(races=len(selected),tickets=len(selected),hits=sum(x[kind+'_return']>0 for x in selected),
        hit_rate=sum(x[kind+'_return']>0 for x in selected)/len(selected) if selected else None,
        stake_yen=stake,return_yen=returned,profit_yen=returned-stake,roi=returned/stake if stake else None,
        max_return_yen=biggest,roi_without_max=(returned-biggest)/(stake-300) if stake>300 else None,
        max_daily_drawdown_yen=worst)

def choose(field,trial):
    score_name={'E01':'existing_basic','E02':'existing_cross','E03':'base','E04':'content','E05':'condition'}.get(trial,'full')
    if int(trial[1:])<=6:
        return sorted(field,key=lambda x:(-x['scores'][score_name],int(x['key'])))[:2]
    anchor=max(field,key=lambda x:(x['scores']['full']*(.85+.15*x['past_consistency']),-int(x['key'])))
    possible=[x for x in field if x is not anchor and 2<=x['price']<=30 and x['scores']['full']>=.15]
    if trial=='E08':
        possible=[x for x in possible if x['restore'] and x['strength_drop']>=.15 and x['scores']['full']>x['scores']['base']]
    if not possible:
        return None
    partner=max(possible,key=lambda x:(x['scores']['full']/min(1,3*x['market_probability']),-int(x['key'])))
    if trial in ['E09','E10'] and (anchor['scores']['full']<.5 or partner['scores']['full']<.25):
        return None
    if trial=='E10' and (6<=int(anchor['race_date'][5:7])<=8 or anchor['newcomer'] or partner['newcomer'] or not anchor['has_history'] or not partner['has_history']):
        return None
    return [anchor,partner]

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    contract=json.loads((OUT/'experiment_contract.json').read_text(encoding='utf-8'))
    rows,races,audit,hashes,maxpast=build_rows()
    train=[r for r in rows if r['split']=='train']
    pred=[r for r in rows if r['split']!='train']
    print('Rows',len(train),len(pred),'audit',dict(audit),flush=True)
    existing=ROOT/'.workstate/jra-srb/jra-o1o2-cross-pool-v1'
    model_dir=OUT/'models'
    model_dir.mkdir(exist_ok=True)
    model_hashes={}
    for kind in ['basic','cross']:
        path=existing/(kind+'.joblib')
        model_hashes[str(path)]=sha256(path)
        model=joblib.load(path)
        probabilities=model.predict_proba(np.asarray([r[kind] for r in pred]))[:,1]
        for r,p in zip(pred,probabilities,strict=True):
            r.setdefault('scores',{})['existing_'+kind]=float(p)
    base_names=['log_win_odds','normalized_win_market_share',*HISTORY_KEYS,'log_o2_marginal_over_o1_share']
    feature_names={}
    for kind in ['base','content','condition','full']:
        model=make_pipeline(SimpleImputer(strategy='mean',add_indicator=True,keep_empty_features=True),
            StandardScaler(),LogisticRegression(C=.1,max_iter=1000,solver='lbfgs',random_state=0))
        model.fit(matrix(train,kind),np.asarray([r['top3'] for r in train]))
        probabilities=model.predict_proba(matrix(pred,kind))[:,1]
        for r,p in zip(pred,probabilities,strict=True):
            r['scores'][kind]=float(p)
        path=model_dir/(kind+'_top3.joblib')
        joblib.dump(model,path)
        model_hashes[str(path)]=sha256(path)
        feature_names[kind]=base_names+(CONTENT_NAMES if kind in ['content','full'] else [])+(CONDITION_NAMES if kind in ['condition','full'] else [])
        print('Fitted',kind,flush=True)
    grouped=defaultdict(list)
    for r in pred:
        grouped[r['race_id']].append(r)
    all_tickets=[]
    trial_results={}
    for trial in ['E'+str(i).zfill(2) for i in range(1,11)]:
        tickets=[]
        for rid,field in grouped.items():
            selected=choose(field,trial)
            if not selected:
                continue
            meta=races[rid]
            pair=tuple(sorted([x['key'] for x in selected],key=int))
            q_available=pair in meta['quinella'] and bool(meta['quinella_payout'])
            ticket=dict(trial=trial,race_id=rid,**{k:meta[k] for k in ['race_date','split','course','surface','distance','summer','newcomer']},
                anchor=selected[0]['key'],partner=selected[1]['key'],
                anchor_top3_probability=selected[0]['scores']['full'],partner_top3_probability=selected[1]['scores']['full'],
                quinella_t30=meta['quinella'].get(pair),
                wide_stake=300,wide_return=meta['wide_payout'].get(pair,0)*3,
                quinella_stake=300 if q_available else 0,quinella_return=meta['quinella_payout'].get(pair,0)*3 if q_available else 0)
            tickets.append(ticket)
        result={}
        for split in ['dev','holdout','later']:
            part=[t for t in tickets if t['split']==split]
            result[split]={kind:summarize(part,kind) for kind in ['wide','quinella']}
            for group in ['course','summer','newcomer']:
                result[split][group]={str(value):{kind:summarize([t for t in part if t[group]==value],kind) for kind in ['wide','quinella']} for value in sorted({t[group] for t in part},key=str)}
            result[split]['month']={month:{kind:summarize([t for t in part if t['race_date'][:7]==month],kind) for kind in ['wide','quinella']} for month in sorted({t['race_date'][:7] for t in part})}
        trial_results[trial]=result
        all_tickets.extend(tickets)
        print(trial,'dev',result['dev']['wide'],'2026',result['holdout']['wide'],flush=True)
    for p,digest in hashes.items():
        assert sha256(Path(p))==digest,'Input changed: '+p
    for p,digest in model_hashes.items():
        assert sha256(Path(p))==digest,'Model changed: '+p
    eligible=[(key,x['dev']['wide']['roi']) for key,x in trial_results.items() if x['dev']['wide']['races']>=30]
    chosen=max(eligible,key=lambda x:x[1])[0] if eligible else None
    report=dict(contract=contract,input_sha256=hashes,model_sha256=model_hashes,
        contract_sha256=sha256(OUT/'experiment_contract.json'),audit=dict(audit),
        feature_names=feature_names,max_used_past_date=maxpast,strict_past_date_assertions=True,
        trials=trial_results,development_selected_trial=chosen,
        selection_status='試作品候補。利益・実運用の成立とは別。',
        model_trials_run=10,source_trace_not_used_as_training_labels=True)
    (OUT/'experiment_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (OUT/'tickets.jsonl').open('w',encoding='utf-8') as f:
        for t in all_tickets:
            f.write(json.dumps(t,ensure_ascii=False,allow_nan=False)+'\n')
    prediction_keys=['race_id','race_date','split','key','price','market_probability','past_consistency',
                     'restore','strength_drop','has_history','newcomer','past_runs','scores']
    with (OUT/'prediction_rows.jsonl').open('w',encoding='utf-8') as f:
        for r in pred:
            f.write(json.dumps({k:r[k] for k in prediction_keys},ensure_ascii=False,allow_nan=False)+'\n')
    print('Selected on dev only:',chosen,flush=True)

if __name__=='__main__':
    main()
