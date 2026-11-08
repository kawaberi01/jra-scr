"""概要: 場・季節別J23診断の全会計/平均/選択lockと代表区間を元行から独立検算する。
作成日: 2026-10-23
入力: spec275診断結果、元30月保存セル、事前protocol。
出力: independent-verification.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_j23_venue_season_20261023.py
注意事項: 原本更新・SQL/API・新規学習なし。検証成果物は新規保存のみ。
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
OUT = ROOT/'artifacts/jra_research/j23_venue_season_20261023'
CASES = ('J23', 'R1', 'M0', 'J01')
VENUES = dict(zip([f'{i:02}' for i in range(1, 11)], ('札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉')))
SEASON_BY_MONTH = ('冬', '冬', '春', '春', '春', '夏', '夏', '夏', '秋', '秋', '秋', '冬')


def check_number(a, b):
    """nullを区別し、別集計した数値が保存値と許容誤差内で一致することを検査する。"""
    assert (a is None and b is None) or (a is not None and b is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)), (a, b)


def check_summary(rows, actual):
    """会計・時系列DD・確率指標を元行から別の集計手順で照合する。"""
    assert len(rows) == actual['races'] and len({r['J23']['race_date'] for r in rows}) == actual['days']
    bets = [r['J23'] for r in rows if r['J23']['stake'] > 0]
    stake = sum(r['stake'] for r in bets)
    payout = sum(r['payout'] for r in bets)
    expected = {'bets': len(bets), 'buy_days': len({r['race_date'] for r in bets}),
                'hits': sum(r['chosen'] == r['winner'] for r in bets), 'stake': stake, 'payout': payout,
                'profit': payout-stake, 'expected_hits': math.fsum(r['ticket_probability'] for r in bets),
                'quoted_expected_payout': math.fsum(r['stake']*r['ticket_probability']*r['ticket_odds'] for r in bets),
                'roi': payout/stake if stake else None}
    ranked = sorted([r['payout'] for r in bets], reverse=True)
    expected['roi_without_largest'] = (payout-sum(ranked[:1]))/stake if stake else None
    expected['roi_without_top3'] = (payout-sum(ranked[:3]))/stake if stake else None
    equity = np.cumsum([0]+[r['payout']-r['stake'] for r in sorted(bets, key=lambda a: (a['race_date'], a['race_key']))])
    expected['max_drawdown_yen'] = int(np.max(np.maximum.accumulate(equity)-equity))
    for key, value in expected.items():
        check_number(value, actual['account'][key])
    assert actual['small_purchase_sample'] == (len(bets) < 30 or expected['buy_days'] < 10 or expected['hits'] < 3)
    assert sorted({r['J23']['race_date'][:7] for r in rows}) == actual['months_present']
    for c in CASES:
        for field, source_field in (('logloss', 'loss'), ('brier', 'brier')):
            mean = math.fsum(r[c][source_field] for r in rows)/len(rows) if rows else None
            check_number(mean, actual['models'][c][field])
            if c != 'J23':
                delta = math.fsum(r['J23'][source_field]-r[c][source_field] for r in rows)/len(rows) if rows else None
                check_number(delta, actual['J23_minus'][c][field])


def check_interval(rows, actual):
    """代表区分の日別ROI/対照差の再標本化区間を保存値から独立に再計算する。"""
    days = sorted({r['J23']['race_date'] for r in rows})
    amounts = np.asarray([[sum(r['J23']['payout'] for r in rows if r['J23']['race_date'] == d),
                           sum(r['J23']['stake'] for r in rows if r['J23']['race_date'] == d),
                           sum(r['J23']['race_date'] == d for r in rows),
                           *[math.fsum(r['J23']['loss']-r[c]['loss'] for r in rows if r['J23']['race_date'] == d) for c in ('M0', 'R1', 'J01')]] for d in days])
    rng = np.random.default_rng(275)
    totals = np.asarray([amounts[rng.integers(len(days), size=len(days))].sum(axis=0) for _ in range(2000)])
    valid = totals[:, 1] > 0
    assert int(valid.sum()) == actual['roi_valid_draws']
    if valid.any():
        assert np.allclose(np.quantile(totals[valid, 0]/totals[valid, 1], [.025, .975]), actual['roi_95'], atol=1e-12, rtol=0)
    for i, c in enumerate(('M0', 'R1', 'J01')):
        assert np.allclose(np.quantile(totals[:, 3+i]/totals[:, 2], [.025, .975]), actual['logloss_difference_95'][c], atol=1e-12, rtol=0)


def main():
    """全区分と選択lockを元保存行から検算し、元SHA不変を確認して新規保存する。"""
    result = json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    protocol = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    all_rows = []
    for p in sorted((SOURCE/'cells').glob('*_J23.json')):
        maps = {c: {r['race_key']: r for r in json.loads((p.parent/(p.name[:7]+'_'+c+'.json')).read_text(encoding='utf-8-sig'))['rows']} for c in CASES}
        for key in sorted(maps['J23']):
            a = {c: maps[c][key] for c in CASES}
            d = a['J23']['race_date']
            a.update(year=d[:4], month=int(d[5:7]), venue=VENUES[key[8:10]], season=SEASON_BY_MONTH[int(d[5:7])-1])
            a['venue_season'] = a['venue']+'・'+a['season']
            all_rows.append(a)
    checked = 0
    sections = []
    for y in ('2024', '2025', '2026'):
        sections.append(([r for r in all_rows if r['year'] == y], result['years'][y]))
        sections.append(([r for r in all_rows if r['year'] == y and 4 <= r['month'] <= 9], result['common_months']['years'][y]))
    for phase in ('selection', 'confirmation_already_seen'):
        sections.append(([r for r in all_rows if (r['J23']['race_date'][:7] <= '2026-03') == (phase == 'selection')], result['phases'][phase]))
    for rows, section in sections:
        check_summary(rows, section['baseline']);checked += 1
        for family, names in protocol['families'].items():
            for name in names:
                check_summary([r for r in rows if r[family] == name], section['groups'][family][name]);checked += 1
    independent_selected = defaultdict(list)
    for family, names in protocol['families'].items():
        for name in names:
            a = result['years']['2024']['groups'][family][name]['account']
            if a['bets'] >= 100 and a['buy_days'] >= 20 and a['hits'] >= 10 and a['roi'] >= 1.05 and a['roi_without_top3'] > 1:
                independent_selected[family].append(name)
        assert independent_selected[family] == result['selection_lock']['selected'][family]
    keys2024 = [r['J23']['race_key'] for r in all_rows if r['year'] == '2024']
    canonical = json.dumps(keys2024, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    assert hashlib.sha256(canonical.encode()).hexdigest() == result['selection_lock']['selection_cohort_sha256']
    assert result['selection_lock'] == json.loads((OUT/'selection-lock.json').read_text(encoding='utf-8'))
    for phase in result['phases']:
        phase_rows = [r for r in all_rows if (r['J23']['race_date'][:7] <= '2026-03') == (phase == 'selection')]
        for family, name in (('venue', '小倉'), ('venue', '福島'), ('venue_season', '中山・秋'), ('season', '夏')):
            rows = [r for r in phase_rows if r[family] == name]
            check_interval(rows, result['phases'][phase]['groups'][family][name]['intervals_exploratory'])
    for p, expected in result['verification']['source_sha256'].items():
        assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == expected
    spec = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/275-J23競馬場季節別の再現性診断.md'
    assert hashlib.sha256(spec.read_bytes()).hexdigest() == protocol['spec_sha256']
    verification = {'status': 'passed', 'all_summaries_independently_checked': checked,
                    'representative_bootstrap_checks': 8, 'source_and_protocol_unchanged': True,
                    'selection_lock_2024_only': True, 'races': len(all_rows), 'adoption': False}
    with (OUT/'independent-verification.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(verification, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(verification, ensure_ascii=False))


if __name__ == '__main__':
    main()
