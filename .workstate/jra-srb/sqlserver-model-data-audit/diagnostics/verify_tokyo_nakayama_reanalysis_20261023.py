"""概要: 東京・中山再分析のledgerを元保存値と照合し、全比較表と代表区間を独立検算する。
作成日: 2026-10-23
入力: spec295成果物、元30月セル、V110買い目、S08競走診断。
出力: independent-verification.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_tokyo_nakayama_reanalysis_20261023.py
注意事項: SQL/API/学習/原本更新なし。既存成果物の上書きなし。
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT/'artifacts/jra_research/tokyo_nakayama_reanalysis_20261023'
SOURCE = ROOT/'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'


def near(a, b):
    """空群nullを区別して数値を照合する。"""
    assert (a is None and b is None) or (a is not None and b is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)), (a, b)


def take(rows, scope, period):
    """記録済み区分名から場・季節・距離・観測群・年を独立に抽出する。"""
    out = []
    words = scope.split('_')
    for r in rows:
        if words[0] != 'both' and r['course'] != words[0]: continue
        if 'autumn' in words and not 9 <= int(r['race_date'][5:7]) <= 11: continue
        if 'long' in words and r.get('distance', 0) <= 2000: continue
        if 'rich' in words and r.get('stratum') != 'rich': continue
        if 'sparse' in words and r.get('stratum') != 'sparse': continue
        if period.isdigit() and r['race_date'][:4] != period: continue
        if period == 'through_2025' and r['race_date'][:4] > '2025': continue
        out.append(r)
    return out


def check_stats(rows, case, s):
    """元対象全体と購入部分を分け、会計・平均・DD・高額除外を別集計する。"""
    v = [r['models'][case] for r in rows]
    bets = [a for a in v if a['stake']]
    stake = sum(a['stake'] for a in v);payout = sum(a['payout'] for a in v)
    assert s['races'] == len(rows) and s['bets'] == len(bets)
    assert s['days'] == len({r['race_date'] for r in rows})
    assert s['buy_days'] == len({r['race_date'] for r in rows if r['models'][case]['stake']})
    assert s['months'] == sorted({r['race_date'][:7] for r in rows})
    assert s['stake'] == stake and s['payout'] == payout and s['profit'] == payout-stake
    assert s['hits'] == sum(a['payout'] > 0 for a in bets)
    near(s['expected_hits'], math.fsum(a['ticket_probability'] for a in bets))
    near(s['logloss'], math.fsum(a['loss'] for a in v)/len(v));near(s['brier'], math.fsum(a['brier'] for a in v)/len(v))
    for count, field in ((0, 'roi'), (1, 'roi_without_largest'), (3, 'roi_without_top3')):
        returned = payout-sum(sorted((a['payout'] for a in bets), reverse=True)[:count])
        near(s[field], returned/stake if stake else None)
    balances = np.cumsum([0]+[r['models'][case]['payout']-r['models'][case]['stake'] for r in sorted(rows, key=lambda r: r['race_key'])])
    assert s['max_drawdown'] == int(np.max(np.maximum.accumulate(balances)-balances))
    near(s['profit_per_race'], (payout-stake)/len(rows))
    near(s['loss_difference_vs_J23'], math.fsum(r['models'][case]['loss']-r['models']['J23']['loss'] for r in rows)/len(rows))
    checks = {'min_bets': len(bets) >= 100, 'min_days': s['buy_days'] >= 30, 'min_hits': s['hits'] >= 10,
              'roi105': s['roi'] is not None and s['roi'] >= 1.05,
              'roi_lower_above100': s['roi_95'] is not None and s['roi_95'][0] > 1}
    assert checks == s['minimum_purchase_checks'] and all(checks.values()) == s['minimum_purchase_checks_passed']


def check_bootstrap(rows, case, s):
    """代表比較の日単位の再標本化を逐次生成し、対応区間を検算する。"""
    days = defaultdict(list)
    for r in rows: days[r['race_date']].append(r)
    values = []
    for d in sorted(days):
        rs = days[d]
        values.append([sum(r['models'][case]['payout'] for r in rs), sum(r['models'][case]['stake'] for r in rs), len(rs),
                       math.fsum(r['models'][case]['loss']-r['models']['J23']['loss'] for r in rs),
                       sum(r['models'][case]['payout']-r['models'][case]['stake']-r['models']['J23']['payout']+r['models']['J23']['stake'] for r in rs)])
    values = np.asarray(values);rng = np.random.default_rng(295)
    totals = np.asarray([values[rng.integers(len(values), size=len(values))].sum(axis=0) for _ in range(2000)])
    valid = totals[:, 1] > 0
    assert s['roi_valid_draws'] == int(valid.sum())
    if valid.any(): assert np.allclose(s['roi_95'], np.quantile(totals[valid, 0]/totals[valid, 1], [.025, .975]), rtol=0, atol=1e-10)
    assert np.allclose(s['loss_difference_95'], np.quantile(totals[:, 3]/totals[:, 2], [.025, .975]), rtol=0, atol=1e-10)
    assert np.allclose(s['profit_difference_per_race_95'], np.quantile(totals[:, 4]/totals[:, 2], [.025, .975]), rtol=0, atol=1e-10)


def main():
    """元保存値・全比較表・代表区間・元SHAと仕様SHAを確認して保存する。"""
    result = json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    panels = json.loads((OUT/'ledger.json').read_text(encoding='utf-8'))
    refs = {c: {} for c in ('J23', 'R1', 'M0', 'J01')}
    for c in refs:
        for p in sorted((SOURCE/'cells').glob('*_'+c+'.json')):
            refs[c].update({r['race_key']: r for r in json.loads(p.read_text(encoding='utf-8-sig'))['rows']})
    vr = json.loads((ROOT/'.workstate/jra-srb/jra-second-ten-nosummer-v1/V110_tickets.json').read_text(encoding='utf-8-sig'))
    vrefs = {r['race_id']: r for stage in ('development', 'exploratory') for r in vr[stage]}
    sr = json.loads((ROOT/'artifacts/jra_research/runs/20261017T091533Z_631037c77cb34fd895c779df1ba77e8d/metrics.json').read_text(encoding='utf-8-sig'))
    srefs = {r['race_key']: r for r in sr['race_diagnostics']}
    source_rows = 0
    for panel, rows in panels.items():
        assert len(rows) == len({r['race_key'] for r in rows})
        for r in rows:
            key = r['race_key'];assert r['course'] == {'05': 'tokyo', '06': 'nakayama'}[key[8:10]]
            assert '2024-04-01' <= r['race_date'] <= '2026-09-30'
            for c in refs:
                for field, value in r['models'][c].items(): near(value, refs[c][key][field])
            if 'V110' in r['models']:
                m, v = vrefs[key], r['models']['V110'];t = m['ticket']
                near(v['loss'], m['loss']);assert v['stake'] == (600 if t else 0) and v['payout'] == (6*t['payout'] if t else 0)
            if 'S08' in r['models']:
                for c, var in (('S08', 'full'), ('S08_history', 'history')):
                    d, v = srefs[key], r['models'][c]
                    near(v['loss'], d['logloss'][var]);near(v['brier'], d['brier'][var])
                    assert v['stake'] == sum(t['stake_yen'] for t in d['tickets'][var])
                    assert v['payout'] == sum(t['payout_yen'] for t in d['tickets'][var])
            source_rows += 1
    counts = 0
    for panel, scopes in result['panels'].items():
        for scope, periods in scopes.items():
            for period, group in periods.items():
                rows = take(panels[panel], scope, period)
                assert len(rows) == group['races']
                for c, s in group['models'].items(): check_stats(rows, c, s);counts += 1
    examples = [('base', 'both_autumn', '2024', 'J23'), ('base', 'both_autumn', '2025', 'J23'),
                ('V110_common', 'tokyo_all', '2025', 'V110'), ('V110_common', 'tokyo_all', '2026', 'V110'),
                ('V110_common', 'nakayama_all', 'all', 'V110'), ('S08_common', 'both_all_rich', '2026', 'S08')]
    for panel, scope, period, case in examples:
        check_bootstrap(take(panels[panel], scope, period), case, result['panels'][panel][scope][period]['models'][case])
    for name, value in result['source_sha256'].items(): assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == value
    protocol = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    spec = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/295-東京中山向け保存研究の固定再分析.md'
    assert hashlib.sha256(spec.read_bytes()).hexdigest() == protocol['spec_sha256']
    out = {'status': 'passed', 'source_ledger_rows_checked': source_rows, 'model_summaries_checked': counts,
           'independent_bootstrap_checks': len(examples), 'source_and_spec_unchanged': True,
           'no_data_after_202609': True, 'adoption': False}
    with (OUT/'independent-verification.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(out, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
