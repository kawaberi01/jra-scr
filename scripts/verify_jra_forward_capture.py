"""概要: 保存事前情報の原本対応・時刻・全組合せと、凍結再集計/版管理結合を検算する。
作成日: 2026-10-25
入力: --run受領監査、--recheck凍結再集計、--versioned版管理監査。
出力: verification.json。成功0、不一致時は非0。
実行例: uv run --frozen --extra ml python scripts/verify_jra_forward_capture.py --run artifacts/jra_research/forward_capture_20261025_v4 --recheck artifacts/jra_research/forward_capture_20261025_recheck --versioned artifacts/jra_research/versioned_links_20261025_v2
注意事項: SQL/HTTP/新学習なし。既使用保存を未知試験へ昇格しない。
"""

import argparse
from collections import Counter
import gzip
from itertools import combinations
import json
from pathlib import Path

from audit_jra_forward_capture import dump,sha,instant,ROOT


def read(path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    """凍結JSONL.gzを読む。"""
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def prices_check(card,odds):
    """全組合せ数・取消以外の馬混入・実価格と現在結果欄の非混入を確認する。"""
    runners=card['runners']
    horses=sorted((f"{int(r['horse_no']):02d}" for r in runners if r['status']=='active'),key=int)
    assert 8<=len(horses)<=18 and len(set(horses))==len(horses)
    for bet,entries in odds.items():
        expected={(h,) for h in horses} if bet=='win' else set(combinations(horses,2))
        assert {tuple(r['combination']) for r in entries}==expected and len(entries)==len(expected)
        assert all(r['odds']>=1 for r in entries)


def verify(args):
    """原本SHA・独立した時点/馬集合確認・再集計一致と集約件数を照合する。"""
    folder=args.run
    for directory in (folder,args.recheck,args.versioned):
        m=read(directory/'manifest.json')
        assert m['status']=='complete' and not (directory/'failure.json').exists()
        assert all(sha(directory/p)==h for p,h in m['files_sha256'].items())
        assert all(sha(ROOT/p)==h for p,h in m['source_sha256'].items())
    for filename in ('inputs.jsonl.gz','rejected-inputs.json','outcomes.json','d0-replay.json','summary.json','D0-input-contract.json'):
        if filename.endswith('.gz'):
            assert gzip.decompress((folder/filename).read_bytes())==gzip.decompress((args.recheck/filename).read_bytes())
        else:
            assert sha(folder/filename)==sha(args.recheck/filename)
    receipts=rows(folder/'receipts.jsonl.gz')
    by_key={r['request_sha256']:r for r in receipts}
    inputs=rows(folder/'inputs.jsonl.gz')
    for row in inputs:
        assert not {'winner','payouts','results'}.intersection(row)
        keys=row['receipt_keys']
        card_receipt=by_key[keys['card']]
        assert row['card']==card_receipt['payload']['card']
        post,decision=instant(row['post_at']),instant(row['decision_at'])
        assert decision<post
        assert instant(card_receipt['received_at_utc'])<=decision
        assert instant(row['card']['fetched_at'])<=min(instant(t) for t in row['observed_at'].values())
        prices_check(row['card'],row['odds'])
        for bet in ('win','quinella'):
            receipt=by_key[keys[bet]]
            assert receipt['race_id']==row['race_id'] and receipt['payload']['odds_timing']==row['timing']
            assert instant(receipt['received_at_utc'])==instant(row['server_received_at'][bet])<post
            assert instant(receipt['payload']['odds']['fetched_at'])==instant(row['observed_at'][bet])<post
            candidates=[r for r in receipts if r['operation']=='odds' and r['race_id']==row['race_id']
                and r['payload']['bet_type']==bet and r['payload']['odds_timing']==row['timing']]
            assert min(candidates,key=lambda r:instant(r['received_at_utc']))['request_sha256']==keys[bet]
            raw=receipt['payload']['odds']
            entries=raw.get('entries') or raw.get('odds',{}).get(bet,[])
            price_map={tuple(sorted((f'{int(h):02d}' for h in e['combination']),key=int)):float(e['odds']) for e in entries}
            assert all(price_map[tuple(e['combination'])]==e['odds'] for e in row['odds'][bet])
    s=read(folder/'summary.json')
    assert s['joined_observations']==len(inputs) and s['joined_races']==len({r['race_id'] for r in inputs})
    assert s['receipt_versions']==dict(Counter(r['operation'] for r in receipts))
    canonical=read(folder/'canonical-results.json')
    complete={r['race_id'] for r in canonical['race_results']} & {r['race_id'] for r in canonical['result_entries']} & {
        r['race_id'] for r in canonical['payouts'] if r['bet_type'] in ('馬連','quinella')}
    assert len(complete)==s['complete_result_races']
    replays=read(folder/'d0-replay.json')
    assert s['D0_reproduced_pairs']==sum(r.get('pairs',0) for r in replays if r['status']=='reproduced')
    versioned=rows(args.versioned/'versioned-inputs.jsonl.gz')
    links=read(args.versioned/'links.json')
    for row in versioned:
        assert row['server_receipt_time_verified'] is False
        assert row['card']['meta']['card_snapshot_id'] is not None
        assert instant(row['card']['meta']['card_fetched_at'])<=min(instant(t) for t in row['observed_at'].values())
        assert max(instant(t) for t in row['observed_at'].values())<instant(row['post_at'])
        prices_check({'runners':row['card']['runners']},row['odds'])
        assert not {'winner','payouts','results'}.intersection(row)
    predictions=rows(folder/'predictions.jsonl.gz')
    by_id={p['prediction_id']:p for p in predictions}
    for link in links:
        assert link['has_complete_result']==(link['race_id'] in complete)
        assert all(by_id[key]['race_id']==link['race_id'] for key in link['saved_prediction_ids'])
    vs=read(args.versioned/'summary.json')
    assert vs['T30_joined_races']==len(versioned)==len(links)
    assert vs['with_complete_result']==sum(l['has_complete_result'] for l in links)
    assert vs['with_prediction_and_result']==sum(l['has_complete_result'] and bool(l['saved_prediction_ids']) for l in links)
    output={'status':'passed','receipt_inputs':len(inputs),'versioned_T30_inputs':len(versioned),
        'frozen_reaggregation_identical':True,'source_times_and_prices_checked':True,
        'D0_saved_probability_checks':s['D0_reproduced_pairs'],'new_SQL_reads':0,'unknown_test':False,
        'verifier_sha256':sha(Path(__file__))}
    dump(folder/'verification.json',output)
    print(json.dumps(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--recheck',type=Path,required=True)
    parser.add_argument('--versioned',type=Path,required=True)
    verify(parser.parse_args())
