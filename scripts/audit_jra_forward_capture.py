"""概要: 既存の未来向け保存を凍結し、事前入力/結果/予測の結合とD0再現性を監査する。
作成日: 2026-10-25
入力: reader設定、--output新規出力先、--from-date/--to-date、spec420。
出力: 受領原本・事前入力・結果の別JSONL.gz、予測再現監査・集計・SHA。
実行例: uv run --frozen --extra ml python scripts/audit_jra_forward_capture.py --output artifacts/jra_research/forward_capture_20261025
注意事項: SQL SELECTのみ。外部HTTP/DB書込み/過去取得/再学習なし。既使用の保存分は未知試験ではない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
from itertools import combinations
import json
from pathlib import Path
import shutil

import joblib
import numpy as np

from jra_srb.storage import build_analysis_store
from jra_srb.storage_config import storage_backend
from jra_srb.jra_odds_timeline import parse_start_datetime
from jra_srb import jra_research_attribute_chimera as model
from jra_srb.jra_research_chimera_thirty_features import pl_pairs
from jra_srb.jra_research_contracts import ResearchError, horse_number
from jra_srb.jra_research_native_card import _official_source_url
from verify_jra_attribute_chimera import independent_predict
from compare_jra_condition_preview import price_array

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT/'artifacts/jra_research/market_attribute_chimera_20261024_v3'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/420-保存済み事前情報の結合とD0入力監査.md'
JST = timezone(timedelta(hours=9))


def sha(path):
    """ファイル全体のSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    """UTF-8の新規JSONファイルを排他作成する。"""
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def jsonl(path, rows):
    """JSONL.gzを新規作成し、SQL原本と入力/結果を別保存する。"""
    assert not path.exists()
    with gzip.open(path, 'wt', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'))+'\n')


def instant(value, sql_utc=False):
    """時刻をUTCへ変換し、SQLのreceived_at_utc以外のnaive時刻は拒否する。"""
    t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if t.tzinfo is None:
        if not sql_utc:
            raise ValueError('timezone_missing')
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def market_entries(odds, bet_type, horses):
    """公式取消だけを除いた実オッズを正規化し、全組合せの過不足を拒否する。"""
    active = set(horses)
    keys = {(h,) for h in horses} if bet_type == 'win' else set(combinations(horses, 2))
    values, excluded = {}, 0
    entries = odds.get('entries') or odds.get('odds', {}).get(bet_type, [])
    for row in entries:
        key = tuple(sorted((horse_number(v) for v in row['combination']), key=int))
        if not set(key).issubset(active):
            excluded += 1
            continue
        if key in values or key not in keys or row.get('bet_type') not in (None, bet_type):
            raise ValueError('market_duplicate_or_mismatched')
        price = float(row['odds'])
        if not np.isfinite(price) or price < 1:
            raise ValueError('market_invalid_price')
        values[key] = price
    if set(values) != keys:
        raise ValueError('market_incomplete')
    return [{'combination': list(k), 'odds': values[k]} for k in sorted(keys)], excluded


def join_inputs(receipts):
    """凍結受領から、結果欄を読まず最初の市場版と当時カードを結合する。"""
    cards, markets = defaultdict(list), defaultdict(dict)
    for receipt in receipts:
        p = receipt['payload']
        if receipt['operation'] == 'race_card':
            cards[receipt['race_id']].append(receipt)
        elif receipt['operation'] == 'odds' and p['bet_type'] in ('win', 'quinella'):
            key = (receipt['race_id'], p['odds_timing'])
            prior = markets[key].get(p['bet_type'])
            if prior is None or receipt['received_at_utc'] < prior['received_at_utc']:
                markets[key][p['bet_type']] = receipt
    joined, rejected = [], []
    for (race_id, timing), market in sorted(markets.items()):
        try:
            if set(market) != {'win', 'quinella'}:
                raise ValueError('win_or_quinella_not_saved')
            observed = {k: instant(r['payload']['odds']['fetched_at']) for k, r in market.items()}
            received = {k: instant(r['received_at_utc']) for k, r in market.items()}
            decision = max(received.values())
            available = [r for r in cards[race_id] if instant(r['received_at_utc']) <= decision
                and instant(r['payload']['card']['fetched_at']) <= min(observed.values())]
            if not available:
                raise ValueError('pre_market_card_not_saved')
            card_receipt = max(available, key=lambda r: (instant(r['payload']['card']['fetched_at']), r['received_at_utc']))
            card = card_receipt['payload']['card']
            status = card.get('data_status') or {}
            if status.get('runner_set') != 'complete' or status.get('source_kind') != 'pre_race_card':
                raise ValueError('card_not_complete_prerace')
            if card['race_id'] != race_id or not _official_source_url(card['source']):
                raise ValueError('card_identity_or_source')
            post = parse_start_datetime(datetime.strptime(race_id[:8], '%Y%m%d').date(), card['start_time'])
            if post is None:
                raise ValueError('post_time_missing')
            if decision >= post or any(t >= post for t in observed.values()):
                raise ValueError('market_received_or_observed_after_post')
            if any(observed[k] > received[k]+timedelta(seconds=2) for k in market):
                raise ValueError('observation_after_receipt')
            if any(r.get('status') not in ('active', 'withdrawn', 'excluded') for r in card['runners']):
                raise ValueError('card_runner_status_unknown')
            runners = sorted((r for r in card['runners'] if r['status'] == 'active'), key=lambda r: int(r['horse_no']))
            horses = [horse_number(r['horse_no']) for r in runners]
            if card['surface'] not in ('芝', 'ダート') or not 8 <= len(horses) <= 18 or len(set(horses)) != len(horses):
                raise ValueError('unsupported_surface_or_roster')
            odds, excluded = {}, {}
            for k, receipt in market.items():
                source = receipt['payload']['odds']
                if source['race_id'] != race_id or not _official_source_url(source['source']):
                    raise ValueError('market_identity_or_source')
                # 名簿にない馬を除くのは、カードで取消が明示された場合だけ。
                source_entries = source.get('entries') or source.get('odds', {}).get(k, [])
                mentioned = {horse_number(h) for v in source_entries for h in v['combination']}
                withdrawn = {horse_number(r['horse_no']) for r in card['runners'] if r['status'] in ('withdrawn', 'excluded')}
                if not mentioned.issubset(set(horses)|withdrawn):
                    raise ValueError('market_unexplained_horse')
                odds[k], excluded[k] = market_entries(source, k, horses)
            joined.append({'race_id': race_id, 'race_date': post.date().isoformat(), 'timing': timing,
                'post_at': post.isoformat(), 'decision_at': decision.isoformat(), 'card': card, 'odds': odds,
                'observed_at': {k: t.isoformat() for k, t in observed.items()},
                'server_received_at': {k: t.isoformat() for k, t in received.items()},
                'market_time_gap_seconds': abs((observed['win']-observed['quinella']).total_seconds()),
                'oldest_market_age_seconds': (decision-min(observed.values())).total_seconds(),
                'minutes_before_post': (post-decision).total_seconds()/60, 'excluded_withdrawn_entries': excluded,
                'receipt_keys': {'card': card_receipt['request_sha256'], **{k:r['request_sha256'] for k,r in market.items()}},
                'd0_history_features_in_capture': False})
        except (ValueError, KeyError, TypeError, ResearchError) as error:
            rejected.append({'race_id': race_id, 'timing': timing, 'reason': getattr(error,'reason',str(error))})
    return joined, rejected


def replay_d0(predictions):
    """保存済みD0の全確率を、保存された当時入力から元式と独立式で再計算する。"""
    fitted = joblib.load(REFERENCE/'final_model.joblib')
    expected_sha = sha(REFERENCE/'final_model.joblib')
    if expected_sha != json.loads((REFERENCE/'model-manifest.json').read_text(encoding='utf-8'))['model_sha256']:
        raise ValueError('reference_model_sha_mismatch')
    rows = []
    for prediction in predictions:
        if 'd0' not in prediction['theory_version'].lower():
            continue
        row = {k: prediction[k] for k in ('prediction_id', 'race_id', 'theory_version', 'created_at')}
        try:
            snapshot, forecast = prediction['snapshot'], prediction['forecast']
            forecast = forecast.get('forecast', forecast)
            if snapshot['model_sha256'] != expected_sha or forecast['model_sha256'] != expected_sha:
                raise ValueError('different_D0_model')
            public, odds = snapshot['public_features'], snapshot['odds']
            horses = public['horses']
            prices = price_array(odds, 'quinella', list(combinations(horses, 2)))
            q = 1/prices
            q /= q.sum()
            record = {**public, 'x': np.asarray(public['x'], dtype=np.float32), 'market': q,
                'pl': pl_pairs(1/price_array(odds, 'win', [(h,) for h in horses])),
                'attributes': np.asarray(snapshot['attributes'], dtype=np.float32), 'race_flags': np.zeros(3, dtype=np.float32)}
            if record['race_id'] != prediction['race_id']:
                raise ValueError('prediction_race_identity')
            p = model.predict(fitted, record)
            np.testing.assert_allclose(p, independent_predict(fitted, record), rtol=1e-12, atol=1e-14)
            saved = {tuple(r['horses']):r['probability'] for r in forecast['pair_ranking']}
            np.testing.assert_allclose(p, [saved[k] for k in combinations(horses, 2)], rtol=1e-12, atol=1e-14)
            post = parse_start_datetime(date.fromisoformat(public['race_date']), snapshot['card']['start_time'])
            row.update({'status': 'reproduced', 'runners': len(horses), 'pairs': len(p),
                'client_created_before_post': bool(post and instant(prediction['created_at']) < post),
                'server_prediction_receipt_verified': False,
                'historical_publication_verified': snapshot['input_quality'].get('historical_publication_verified', False),
                'history_raw_latest': {k:v.get('latest_raw_day') for k,v in snapshot['input_quality'].get('additional_coverage', {}).items()},
                'new_prospective_trial_claimed': False})
        except Exception as error:
            row.update({'status': 'not_reproduced', 'reason': type(error).__name__})
        rows.append(row)
    return rows


def complete_result_ids(canonical):
    """保存結果・順位・馬連払戻の共通IDを求め、対象外の枠連等を解釈しない。"""
    race_ids={r['race_id'] for r in canonical['race_results']}
    ranks_ids={r['race_id'] for r in canonical['result_entries']}
    payouts_ids={r['race_id'] for r in canonical['payouts'] if r['bet_type'] in ('quinella','馬連')}
    return race_ids & ranks_ids & payouts_ids


def capture(folder, start, end):
    """既存SQLをreaderで上限付き取得し、基準時刻以前の受領原本を凍結する。"""
    if storage_backend() != 'sqlserver':
        raise ValueError('expected_existing_sqlserver_backend')
    cutoff = datetime.now(timezone.utc)
    bounds = (start.strftime('%Y%m%d')+'0000', (end+timedelta(days=1)).strftime('%Y%m%d')+'0000')
    store = build_analysis_store()
    with store._connect(read_only=True) as c:
        receipts = []
        for operation in ('race_card', 'odds', 'race_result'):
            rows = c._raw('SELECT TOP (5001) request_sha256,operation,race_id,payload_json,received_at_utc '
                'FROM api_runtime.write_receipts WHERE operation=? AND race_id>=? AND race_id<? AND received_at_utc<=? '
                'ORDER BY received_at_utc,request_sha256', (operation,*bounds,cutoff.replace(tzinfo=None))).fetchall()
            if len(rows) > 5000:
                raise ValueError('receipt_row_limit')
            receipts.extend({'request_sha256': bytes(r['request_sha256']).hex(), 'operation':r['operation'],
                'race_id':r['race_id'], 'received_at_utc':instant(r['received_at_utc'],sql_utc=True).isoformat(),
                'payload':json.loads(r['payload_json'])} for r in rows)
        pred_rows = c._raw('SELECT TOP (5001) prediction_id,race_id,theory_version,created_at,pre_race_snapshot_json,prediction_json '
            'FROM api_runtime.predictions WHERE race_id>=? AND race_id<? ORDER BY created_at,prediction_id', bounds).fetchall()
        if len(pred_rows) > 5000:
            raise ValueError('prediction_row_limit')
        predictions = [{k:r[k] for k in ('prediction_id','race_id','theory_version','created_at')}|
            {'snapshot':json.loads(r['pre_race_snapshot_json']), 'forecast':json.loads(r['prediction_json'])} for r in pred_rows
            if instant(r['created_at']) <= cutoff]
        canonical = {}
        for table in ('race_results', 'result_entries', 'payouts'):
            rows = c._raw(f'SELECT TOP (5001) * FROM api_runtime.{table} WHERE race_id>=? AND race_id<?', bounds).fetchall()
            if len(rows) > 5000:
                raise ValueError('result_row_limit')
            canonical[table] = [dict(r) for r in rows]
    jsonl(folder/'receipts.jsonl.gz', receipts)
    jsonl(folder/'predictions.jsonl.gz', predictions)
    dump(folder/'canonical-results.json', canonical)
    dump(folder/'capture.json', {'from_date':start.isoformat(),'to_date':end.isoformat(),'cutoff_utc':cutoff.isoformat(),
        'backend':'sqlserver','read_only':True,'new_external_requests':0,'new_sql_writes':0,
        'per_kind_row_limit':5000,'cross_table_transaction_snapshot_claimed':False})
    return receipts, predictions, canonical


def analyze(folder, receipts, predictions, canonical):
    """凍結入力だけから結合件数、結果/予測との対応とD0特徴の対応表を作る。"""
    joined, rejected = join_inputs(receipts)
    canonical_ids = {r['race_id'] for r in canonical['race_results']}
    result_receipts = {r['race_id'] for r in receipts if r['operation']=='race_result'}
    complete_outcomes = complete_result_ids(canonical)
    pred_ids = {r['race_id'] for r in predictions}
    by_date = defaultdict(lambda:Counter())
    for row in joined:
        counter = by_date[row['race_date']]
        counter['joined_observations'] += 1
        counter['with_complete_result'] += row['race_id'] in complete_outcomes
        counter['with_saved_prediction'] += row['race_id'] in pred_ids
    jsonl(folder/'inputs.jsonl.gz', joined)
    dump(folder/'rejected-inputs.json', rejected)
    # 結果と払戻は入力とは別出力。元結果の既知性を消さない。
    dump(folder/'outcomes.json', {'race_results':canonical['race_results'],'entries':canonical['result_entries'],'payouts':canonical['payouts']})
    replays = replay_d0(predictions)
    dump(folder/'d0-replay.json', replays)
    raw_cards = [r['payload']['card'] for r in receipts if r['operation']=='race_card']
    native_id_count = sum(bool(r.get('horse_id')) for c in raw_cards for r in c['runners'])
    direct_x_count = sum(bool(c.get('public_features',{}).get('x')) for c in raw_cards)
    summary = {'receipt_versions':dict(Counter(r['operation'] for r in receipts)),
        'receipt_races':{op:len({r['race_id'] for r in receipts if r['operation']==op}) for op in ('race_card','odds','race_result')},
        'joined_observations':len(joined),'joined_races':len({r['race_id'] for r in joined}),
        'rejected_observations':len(rejected),'rejection_reasons':dict(Counter(r['reason'] for r in rejected)),
        'complete_result_races':len(complete_outcomes),'result_receipt_races':len(result_receipts),
        'joined_races_with_result':len({r['race_id'] for r in joined} & complete_outcomes),
        'saved_predictions':len(predictions),'prediction_races':len(pred_ids),
        'joined_races_with_prediction':len({r['race_id'] for r in joined} & pred_ids),
        'joined_races_with_prediction_and_result':len({r['race_id'] for r in joined}&pred_ids&complete_outcomes),
        'by_date':dict(by_date),'D0_replay_status':dict(Counter(r['status'] for r in replays)),
        'D0_reproduced_races':len({r['race_id'] for r in replays if r['status']=='reproduced'}),
        'D0_reproduced_pairs':sum(r.get('pairs',0) for r in replays if r['status']=='reproduced'),
        'D0_reproduced_with_result':len({r['race_id'] for r in replays if r['status']=='reproduced'}&complete_outcomes),
        'active_runner_observations':sum(sum(r['status']=='active' for r in row['card']['runners']) for row in joined),
        'runners_with_recent_races':sum(sum(r['status']=='active' and bool(r.get('official_recent_races')) for r in row['card']['runners']) for row in joined),
        'raw_card_runner_native_id_count':native_id_count,'raw_card_direct_d0_x_count':direct_x_count,
        'raw_card_has_native_horse_id':native_id_count>0,'raw_card_has_D0_history_x':direct_x_count>0,
        'unknown_test':False,'performance_adoption_claimed':False,'new_training':0}
    dump(folder/'summary.json', summary)
    dump(folder/'D0-input-contract.json', {'available_from_saved_card_odds':['race_id/date/course/surface/distance','six_current_attributes','win/quinella_market','official_recent_races'],
        'not_equivalent_to_saved_recent_races':list(model.core.base.FEATURES),
        'missing_direct_fields':['native_horse_id','D0_15_column_state_features'],
        'saved_D0_predictions_with_public_features':'replayed separately; not recreated by zero filling',
        'next_scope':'audit a new input contract using captured public data or explicit accumulated history; do not require reacquiring unavailable past'})
    return summary


def run(args):
    """受領凍結と再計算を実行し、失敗時は理由の型だけを保存して停止する。"""
    folder = args.output
    folder.mkdir(parents=True, exist_ok=False)
    try:
        source_paths = [Path(__file__),SPEC,Path(model.__file__),ROOT/'src/jra_srb/analysis_store.py',ROOT/'src/jra_srb/sqlserver_store.py',ROOT/'src/jra_srb/jra_odds_timeline.py']
        sources = {str(p.relative_to(ROOT)):sha(p) for p in source_paths}
        if args.frozen_source is None:
            receipts,predictions,canonical = capture(folder,date.fromisoformat(args.from_date),date.fromisoformat(args.to_date))
        else:
            names=('receipts.jsonl.gz','predictions.jsonl.gz','canonical-results.json','capture.json')
            for name in names:
                shutil.copy2(args.frozen_source/name,folder/name)
                if sha(args.frozen_source/name)!=sha(folder/name):
                    raise ValueError('frozen_copy_changed')
            with gzip.open(folder/'receipts.jsonl.gz','rt',encoding='utf-8') as stream:
                receipts=[json.loads(line) for line in stream]
            with gzip.open(folder/'predictions.jsonl.gz','rt',encoding='utf-8') as stream:
                predictions=[json.loads(line) for line in stream]
            canonical=json.loads((folder/'canonical-results.json').read_text(encoding='utf-8'))
            dump(folder/'frozen-origin.json',{'source':str(args.frozen_source),
                'files_sha256':{name:sha(folder/name) for name in names},'new_sql_reads':0})
        summary = analyze(folder,receipts,predictions,canonical)
        if any(sha(ROOT/p)!=h for p,h in sources.items()):
            raise ValueError('source_changed')
        dump(folder/'manifest.json',{'status':'complete','source_sha256':sources,
            'files_sha256':{p.name:sha(p) for p in folder.iterdir() if p.is_file()},'D0_model_sha256':sha(REFERENCE/'final_model.joblib')})
        print(json.dumps(summary,ensure_ascii=False))
    except Exception as error:
        dump(folder/'failure.json',{'type':type(error).__name__,'message':str(error) if isinstance(error,(ValueError,AssertionError)) else 'inspect local traceback; connection secrets not logged'})
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--from-date',default='2026-10-01')
    parser.add_argument('--to-date',default='2026-10-25')
    parser.add_argument('--frozen-source',type=Path)
    run(parser.parse_args())
