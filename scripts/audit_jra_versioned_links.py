"""概要: 受領原本以前からの版管理カード/オッズをT30で結合し、保存結果・予測との対応を確認する。
作成日: 2026-10-25
入力: --base-run凍結監査、既存reader設定、--output新規出力先。
出力: 版管理T30入力JSONL.gz、対象外台帳、結果/予測対応、SHA。
実行例: uv run --frozen --extra ml python scripts/audit_jra_versioned_links.py --base-run artifacts/jra_research/forward_capture_20261025_v3 --output artifacts/jra_research/versioned_links_20261025
注意事項: SQL SELECTのみ。サーバー受領がない版を受領証拠付きと扱わない。外部取得/新学習なし。
"""

import argparse
from collections import Counter
from datetime import date,datetime,timezone
import json
from pathlib import Path

from jra_srb.storage import build_analysis_store
from jra_srb.jra_odds_timeline import parse_start_datetime
from jra_srb.jra_research_contracts import horse_number
from audit_jra_forward_capture import dump,jsonl,sha,instant,market_entries,complete_result_ids,ROOT,SPEC


def one(store,key,cutoff):
    """観測時刻から最初のT30市場と直前カードを選び、受領証拠とは区別する。"""
    latest=store.get_pre_race_snapshot(key,include_odds=False,as_of=cutoff)
    post=parse_start_datetime(latest.race.race_date,latest.race.start_time)
    if post is None:
        raise ValueError('post_time_missing')
    selected={}
    for bet in ('win','quinella'):
        snapshots=store.get_odds_timeline(key,bet).snapshots
        candidates=[s for s in snapshots if s.odds_timing=='t_minus_30m' and s.fetched_at and instant(s.fetched_at)<=cutoff]
        if not candidates:
            raise ValueError('T30_market_not_saved')
        selected[bet]=min(candidates,key=lambda s:(instant(s.fetched_at),s.snapshot_id))
    observed={k:instant(s.fetched_at) for k,s in selected.items()}
    card=store.get_pre_race_snapshot(key,include_odds=False,as_of=min(observed.values()))
    if card.meta.card_snapshot_id is None or card.meta.runner_set_status!='complete':
        raise ValueError('asof_card_not_saved')
    post=parse_start_datetime(card.race.race_date,card.race.start_time)
    if post is None or max(observed.values())>=post:
        raise ValueError('observed_after_post')
    if str(card.race.surface) not in ('芝','ダート','turf','dirt'):
        raise ValueError('unsupported_surface')
    runners=[r.model_dump(mode='json') for r in card.runners]
    if any(r['status'] not in ('active','withdrawn','excluded') for r in runners):
        raise ValueError('unknown_runner_status')
    horses=sorted([horse_number(r['horse_no']) for r in runners if r['status']=='active'],key=int)
    if not 8<=len(horses)<=18 or len(set(horses))!=len(horses):
        raise ValueError('unsupported_roster')
    odds,excluded={},{ }
    withdrawn={horse_number(r['horse_no']) for r in runners if r['status'] in ('withdrawn','excluded')}
    for bet,snapshot in selected.items():
        entries=[v.model_dump(mode='json') for v in snapshot.entries]
        mentioned={horse_number(h) for v in entries for h in v['combination']}
        if not mentioned.issubset(set(horses)|withdrawn):
            raise ValueError('unexplained_market_horse')
        odds[bet],excluded[bet]=market_entries({'entries':entries},bet,horses)
    return {'race_id':key,'race_date':card.race.race_date.isoformat(),'timing':'t_minus_30m',
        'card':card.model_dump(mode='json'),'odds':odds,'post_at':post.isoformat(),
        'observed_at':{k:v.isoformat() for k,v in observed.items()},
        'observation_cutoff':max(observed.values()).isoformat(),
        'market_snapshot_ids':{k:v.snapshot_id for k,v in selected.items()},
        'excluded_withdrawn_entries':excluded,'server_receipt_time_verified':False,
        'provenance':'versioned_store_observed_timestamps_only','replay_not_original_prediction':True}


def run(args):
    """既存保存分を上限付きで読み、原本監査と異なる来歴で対応可能性を集計する。"""
    folder=args.output
    folder.mkdir(parents=True,exist_ok=False)
    try:
        base_manifest=json.loads((args.base_run/'manifest.json').read_text(encoding='utf-8'))
        if base_manifest['status']!='complete' or (args.base_run/'failure.json').exists():
            raise ValueError('base_audit_not_complete')
        capture=json.loads((args.base_run/'capture.json').read_text(encoding='utf-8'))
        cutoff=instant(capture['cutoff_utc'])
        store=build_analysis_store()
        with store._connect(read_only=True) as c:
            rows=c._raw('SELECT DISTINCT race_date FROM api_runtime.race_card_snapshots WHERE race_date>=? AND race_date<=? ORDER BY race_date',
                (capture['from_date'],capture['to_date'])).fetchall()
        days=[date.fromisoformat(r[0]) for r in rows]
        targets=[key for day in days for key in store.list_pre_race_race_ids(day)]
        if len(targets)>500:
            raise ValueError('target_limit')
        inputs,rejected=[],[]
        for key in targets:
            try:
                inputs.append(one(store,key,cutoff))
            except Exception as error:
                rejected.append({'race_id':key,'reason':getattr(error,'reason',str(error)) if isinstance(error,(ValueError,LookupError)) else type(error).__name__})
        canonical=json.loads((args.base_run/'canonical-results.json').read_text(encoding='utf-8'))
        outcomes=complete_result_ids(canonical)
        import gzip
        with gzip.open(args.base_run/'predictions.jsonl.gz','rt',encoding='utf-8') as stream:
            predictions=[json.loads(line) for line in stream]
        by_id={}
        for p in predictions:
            by_id.setdefault(p['race_id'],[]).append(p)
        for row in inputs:
            row['saved_prediction_ids']=[p['prediction_id'] for p in by_id.get(row['race_id'],[])]
            # ここは結合メタデータ。結果の値/払戻を入力へ入れない。
        jsonl(folder/'versioned-inputs.jsonl.gz',inputs)
        dump(folder/'rejected.json',rejected)
        links=[{'race_id':r['race_id'],'has_complete_result':r['race_id'] in outcomes,
            'saved_prediction_ids':r['saved_prediction_ids']} for r in inputs]
        dump(folder/'links.json',links)
        summary={'stored_card_races_examined':len(targets),'T30_joined_races':len(inputs),
            'rejected_races':len(rejected),'rejection_reasons':dict(Counter(r['reason'] for r in rejected)),
            'T30_by_date':dict(Counter(r['race_date'] for r in inputs)),
            'with_complete_result':sum(r['has_complete_result'] for r in links),
            'with_saved_prediction':sum(bool(r['saved_prediction_ids']) for r in links),
            'with_prediction_and_result':sum(r['has_complete_result'] and bool(r['saved_prediction_ids']) for r in links),
            'D0_15_features_reconstructed_from_card':False,'server_receipt_evidence_claimed':False,
            'performance_superiority_claimed':False,'unknown_test':False,'new_external_requests':0,'new_sql_writes':0}
        dump(folder/'summary.json',summary)
        dump(folder/'manifest.json',{'status':'complete','source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),SPEC)},
            'base_run':str(args.base_run),'base_manifest_sha256':sha(args.base_run/'manifest.json'),
            'cutoff_utc':capture['cutoff_utc'],'files_sha256':{p.name:sha(p) for p in folder.iterdir() if p.is_file()}})
        print(json.dumps(summary,ensure_ascii=False))
    except Exception as error:
        dump(folder/'failure.json',{'type':type(error).__name__})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
