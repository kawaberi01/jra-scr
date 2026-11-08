"""概要: J23/V110の共通保存予測から実馬番号ペアと損失/損益の重なりを診断する。
作成日: 2026-10-23
入力: spec300、検証済み067 ledger/source SHA、元J23セル/V110分布と買い目。
出力: j23_v110_complementarity_20261023のprotocol・復元行・重複診断。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/diagnose_j23_v110_overlap_20261023.py
注意事項: 全期間既使用の探索。新政策はこの段階で計算しない。SQL/API/学習/元更新なし。
"""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
PRIOR = ROOT/'artifacts/jra_research/tokyo_nakayama_reanalysis_20261023'
OUT = ROOT/'artifacts/jra_research/j23_v110_complementarity_20261023'
SOURCE = ROOT/'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
VROOT = ROOT/'.workstate/jra-srb/jra-second-ten-nosummer-v1'
PERIODS = ('2024', '2025', '2026', 'through_2025', 'all')
STATES = ('neither', 'J23_only', 'V110_only', 'both_same', 'both_different')


def sha(path):
    """ファイル内容のSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    """有限JSONの新規成果物だけをUTF-8で保存する。"""
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def select(rows, period, *, autumn=False, tokyo=True):
    """結果に依存しない固定期間・秋・東京条件で部分集合を返す。"""
    return [r for r in rows if (not tokyo or r['course'] == 'tokyo')
            and (not autumn or 9 <= int(r['race_date'][5:7]) <= 11)
            and (period == 'all' or period == 'through_2025' and r['race_date'] < '2026-01-01'
                 or r['race_date'][:4] == period)]


def correlation(a, b):
    """2変量のPearson相関を返し、定数または少数は未定義とする。"""
    return float(np.corrcoef(a, b)[0, 1]) if len(a) >= 2 and np.std(a) > 0 and np.std(b) > 0 else None


def restore():
    """067の整合済み対象だけで元選択indexを馬番号ペアへ復元し精算を照合する。"""
    previous = json.loads((PRIOR/'results.json').read_text(encoding='utf-8'))
    assert json.loads((PRIOR/'independent-verification.json').read_text(encoding='utf-8'))['status'] == 'passed'
    hashes = dict(previous['source_sha256'])
    for path in (PRIOR/'ledger.json', PRIOR/'results.json', PRIOR/'independent-verification.json'):
        hashes[str(path.relative_to(ROOT))] = sha(path)
    assert all(sha(ROOT/p) == h for p, h in hashes.items())
    ledger = {r['race_key']: r for r in json.loads((PRIOR/'ledger.json').read_text(encoding='utf-8'))['V110_common']}
    originals = {}
    for path in sorted((SOURCE/'cells').glob('*_J23.json')):
        originals.update({r['race_key']: r for r in json.loads(path.read_text(encoding='utf-8-sig'))['rows']})
    meta_json = json.loads((VROOT/'V110_tickets.json').read_text(encoding='utf-8-sig'))
    meta = {r['race_id']: r for part in ('development', 'exploratory') for r in meta_json[part]}
    output = []
    with gzip.open(VROOT/'predictions.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            d = json.loads(line);key = d['race_id']
            if d['trial'] != 'V110' or key not in ledger: continue
            r, j, v = ledger[key], originals[key], meta[key]['ticket']
            keys = [list(map(int, str(k).split('-'))) for k in d['keys']]
            jp = keys[j['chosen']] if j['stake'] else None
            vp = list(map(int, v['key'].split('-'))) if v else None
            assert bool(j['stake']) == (j['chosen'] is not None)
            assert vp is None or vp == keys[v['index']]
            winner = keys[j['winner']]
            models = {c: {**r['models'][c], 'pair': pair} for c, pair in (('J23', jp), ('V110', vp))}
            for c, t in models.items():
                assert t['stake'] in (0, 600) and t['payout'] == (6*j['hr_payout_yen'] if t['pair'] == winner else 0)
                t['hit'] = t['payout'] > 0
            if jp is None: state = 'neither' if vp is None else 'V110_only'
            elif vp is None: state = 'J23_only'
            else: state = 'both_same' if jp == vp else 'both_different'
            assert state != 'both_same' or models['J23']['payout'] == models['V110']['payout']
            assert state != 'both_different' or not (models['J23']['hit'] and models['V110']['hit'])
            output.append({'race_key': key, 'race_date': r['race_date'], 'course': r['course'], 'state': state,
                           'winner_pair': winner, 'hr_payout_yen': j['hr_payout_yen'], 'models': models,
                           'market_loss': r['models']['M0']['loss']})
    assert len(output) == len({r['race_key'] for r in output}) == 946
    return sorted(output, key=lambda r: r['race_key']), hashes


def describe(rows):
    """5群の購入/的中、モデル損失相関と日別の損益/同時損失を要約する。"""
    groups = {}
    for state in STATES:
        subset = [r for r in rows if r['state'] == state]
        s = {'races': len(subset), 'days': len({r['race_date'] for r in subset}), 'models': {}}
        for c in ('J23', 'V110'):
            values = [r['models'][c] for r in subset]
            stake = sum(v['stake'] for v in values);payout = sum(v['payout'] for v in values)
            s['models'][c] = {'bets': sum(v['stake'] > 0 for v in values), 'hits': sum(v['hit'] for v in values),
                               'stake': stake, 'payout': payout, 'profit': payout-stake, 'roi': payout/stake if stake else None}
        groups[state] = s
    assert sum(s['races'] for s in groups.values()) == len(rows)
    days = defaultdict(lambda: [0, 0])
    for r in rows:
        for i, c in enumerate(('J23', 'V110')): days[r['race_date']][i] += r['models'][c]['payout']-r['models'][c]['stake']
    day_values = [v for _, v in sorted(days.items())]
    residual_j = [r['models']['J23']['loss']-r['market_loss'] for r in rows]
    residual_v = [r['models']['V110']['loss']-r['market_loss'] for r in rows]
    jhits = sum(r['models']['J23']['hit'] for r in rows);vhits = sum(r['models']['V110']['hit'] for r in rows)
    samehits = sum(r['models']['J23']['hit'] and r['models']['V110']['hit'] for r in rows)
    jbets = sum(r['models']['J23']['stake'] > 0 for r in rows);vbets = sum(r['models']['V110']['stake'] > 0 for r in rows)
    both = groups['both_same']['races']+groups['both_different']['races']
    return {'races': len(rows), 'groups': groups, 'J23_bets': jbets, 'V110_bets': vbets,
            'both_buy': both, 'same_pair_fraction_when_both_buy': groups['both_same']['races']/both if both else None,
            'both_hit': samehits, 'J23_unique_hit': jhits-samehits, 'V110_unique_hit': vhits-samehits,
            'union_hit_races': jhits+vhits-samehits,
            'raw_loss_correlation': correlation([r['models']['J23']['loss'] for r in rows], [r['models']['V110']['loss'] for r in rows]),
            'market_residual_loss_correlation': correlation(residual_j, residual_v),
            'daily_profit_correlation': correlation([v[0] for v in day_values], [v[1] for v in day_values]),
            'days': len(days), 'both_negative_days': sum(a < 0 and b < 0 for a, b in day_values),
            'J23_positive_V110_negative_days': sum(a > 0 and b < 0 for a, b in day_values),
            'V110_positive_J23_negative_days': sum(b > 0 and a < 0 for a, b in day_values),
            'daily_profits': {k: {'J23': v[0], 'V110': v[1]} for k, v in sorted(days.items())}}


def main():
    """診断仕様を先に保存し、結果から新政策を計算せず重複診断だけを出力する。"""
    OUT.mkdir(exist_ok=True)
    spec = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/300-J23V110買い目重複と単一使い分け検証.md'
    save('diagnostic-protocol.json', {'spec_sha256': sha(spec), 'periods': PERIODS, 'groups': STATES,
                                      'scopes': ['tokyo_all', 'tokyo_autumn'], 'new_policy_evaluations': 0})
    rows, hashes = restore()
    results = {scope: {p: describe(select(rows, p, autumn=scope == 'tokyo_autumn')) for p in PERIODS}
               for scope in ('tokyo_all', 'tokyo_autumn')}
    assert all(sha(ROOT/p) == h for p, h in hashes.items())
    save('rows.json', rows);save('diagnosis.json', {'scopes': results, 'source_sha256': hashes, 'source_unchanged': True})
    print(json.dumps({scope: {p: {k:v for k,v in s.items() if k not in ('groups', 'daily_profits')} for p,s in periods.items()}
                      for scope, periods in results.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
