"""概要: 保存版の時点選択・発走後拒否・公式取消と欠測の区別を確認する。
作成日: 2026-10-25
入力: 人工8頭カード/単勝馬連受領。
出力: pytest成否。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_forward_capture_audit.py
注意事項: SQL/HTTP/学習/購入なし。
"""

from copy import deepcopy
from itertools import combinations
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import audit_jra_forward_capture as audit


def receipts():
    """10時発走に対する9時30分の正常な保存版を返す。"""
    key='202610250501'
    source='https://www.jra.go.jp/JRADB/accessD.html'
    card={'race_id':key,'source':source,'start_time':'10時00分','fetched_at':'2026-10-25T00:29:00Z',
        'surface':'芝','data_status':{'runner_set':'complete','source_kind':'pre_race_card'},
        'runners':[{'horse_no':str(i),'status':'active','official_recent_races':[]} for i in range(1,9)]}
    rows=[{'race_id':key,'operation':'race_card','request_sha256':'card-original',
        'received_at_utc':'2026-10-25T00:29:01+00:00','payload':{'card':card}}]
    for k,second in [('win',0),('quinella',1)]:
        keys=[(i,) for i in range(1,9)] if k=='win' else list(combinations(range(1,9),2))
        odds={'race_id':key,'source':source,'fetched_at':f'2026-10-25T00:30:0{second}Z',
            'entries':[{'combination':list(map(str,p)),'bet_type':k,'odds':'5.0'} for p in keys]}
        rows.append({'race_id':key,'operation':'odds','request_sha256':k,
            'received_at_utc':f'2026-10-25T00:30:0{second+1}+00:00',
            'payload':{'odds':odds,'bet_type':k,'odds_timing':'t_minus_30m'}})
    return rows


def test_asof_card_and_first_market_version():
    """後から届いたカード/オッズで当時の入力を置き換えない。"""
    rows=receipts()
    future=deepcopy(rows[0])
    future['payload']['card']['fetched_at']='2026-10-25T00:31:00Z'
    future['received_at_utc']='2026-10-25T00:31:01+00:00'
    future['request_sha256']='future-card'
    rows.append(future)
    later=deepcopy(rows[1]); later['received_at_utc']='2026-10-25T00:31:02+00:00'; later['request_sha256']='later-win'; rows.append(later)
    joined,rejected=audit.join_inputs(rows)
    assert not rejected and len(joined)==1
    assert joined[0]['receipt_keys']['card']=='card-original' and joined[0]['receipt_keys']['win']=='win'
    assert 'payouts' not in joined[0] and 'winner' not in joined[0]


def test_after_post_and_incomplete_market_reject():
    """時点ラベルがT30でも受領が発走後なら拒否し、不足オッズを補わない。"""
    rows=receipts(); rows[1]['received_at_utc']='2026-10-25T01:00:00+00:00'
    assert audit.join_inputs(rows)[1][0]['reason']=='market_received_or_observed_after_post'
    rows=receipts(); rows[2]['payload']['odds']['entries'].pop()
    assert audit.join_inputs(rows)[1][0]['reason']=='market_incomplete'


def test_explicit_withdrawal_only():
    """カードで取消が明示された馬の行だけを除き、未知の馬は拒否する。"""
    rows=receipts()
    rows[0]['payload']['card']['runners'].append({'horse_no':'9','status':'withdrawn'})
    rows[1]['payload']['odds']['entries'].append({'combination':['9'],'bet_type':'win','odds':'5.0'})
    joined,rejected=audit.join_inputs(rows)
    assert not rejected and joined[0]['excluded_withdrawn_entries']['win']==1
    rows[0]['payload']['card']['runners'].pop()
    assert audit.join_inputs(rows)[1][0]['reason']=='market_unexplained_horse'


def test_invalid_source_number_stays_in_rejection_ledger():
    """馬番号として解釈できない原本行を検出し、その時点を理由付きで残す。"""
    rows=receipts()
    rows[2]['payload']['odds']['entries'][0]['combination']=['','2']
    joined,rejected=audit.join_inputs(rows)
    assert not joined and rejected[0]['reason']=='invalid_horse_number'


def test_japanese_payout_and_unrelated_frame_bet():
    """保存払戻の日本語馬連を認識し、別券種の枠連に影響されない。"""
    canonical={'race_results':[{'race_id':'a'},{'race_id':'b'}],
        'result_entries':[{'race_id':'a'},{'race_id':'b'}],
        'payouts':[{'race_id':'a','bet_type':'枠連'},{'race_id':'a','bet_type':'馬連'},
            {'race_id':'b','bet_type':'quinella'}]}
    assert audit.complete_result_ids(canonical)=={'a','b'}
