"""概要: J23/V110重複診断と単一使い分けの元会計/選択規則/全比較/代表区間を独立検算する。
作成日: 2026-10-23
入力: spec300成果物、067元ledger、J23/V110保存予測。
出力: independent-verification.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_j23_v110_complementarity_20261023.py
注意事項: SQL/API/学習/元更新なし。検証成果物は新規保存のみ。
"""

from collections import defaultdict
import hashlib
import json
import math

import numpy as np

import diagnose_j23_v110_overlap_20261023 as d
import evaluate_j23_v110_veto_20261023 as e


def near(a, b):
    """未定義を区別して別計算の数値を照合する。"""
    assert (a is None and b is None) or (a is not None and b is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)), (a, b)


def independent_subset(rows, scope, period):
    """場/月/年の条件を実行関数に依存せず適用する。"""
    selected = []
    for r in rows:
        if scope.startswith('tokyo') and r['course'] != 'tokyo': continue
        if scope.startswith('nakayama') and r['course'] != 'nakayama': continue
        if scope.endswith('autumn') and int(r['race_date'][5:7]) not in [9, 10, 11]: continue
        if period.isdigit() and r['race_date'][:4] != period: continue
        if period == 'through_2025' and r['race_date'][:4] > '2025': continue
        selected.append(r)
    return selected


def check_stats(rows, name, actual):
    """元競走数・会計・日末DD・高額除外と最低条件を別手順で照合する。"""
    bets = [r for r in rows if r['policies'][name]['stake']]
    stake = sum(r['policies'][name]['stake'] for r in rows)
    payout = sum(r['policies'][name]['payout'] for r in rows)
    assert actual['races'] == len(rows) and actual['bets'] == len(bets)
    assert actual['days'] == len({r['race_date'] for r in rows})
    assert actual['buy_days'] == len({r['race_date'] for r in bets})
    assert actual['hits'] == sum(r['policies'][name]['payout'] > 0 for r in bets)
    assert (actual['stake'], actual['payout'], actual['profit']) == (stake, payout, payout-stake)
    near(actual['profit_per_race'], (payout-stake)/len(rows) if rows else None)
    near(actual['bet_coverage'], len(bets)/len(rows) if rows else None)
    top = sorted((r['policies'][name]['payout'] for r in bets), reverse=True)
    for n, key in ((0, 'roi'), (1, 'roi_without_largest'), (3, 'roi_without_top3')):
        near(actual[key], (payout-sum(top[:n]))/stake if stake else None)
    day_values = []
    for day in sorted({r['race_date'] for r in rows}):
        day_values.append(sum(r['policies'][name]['payout']-r['policies'][name]['stake'] for r in rows if r['race_date'] == day))
    peak = balance = dd = 0
    for value in day_values:
        balance += value;peak = max(peak, balance);dd = max(dd, peak-balance)
    assert actual['max_drawdown_daily'] == dd and actual['worst_day_profit'] == (min(day_values) if day_values else None)
    if rows:
        checks = {'bets100': len(bets) >= 100, 'days30': actual['buy_days'] >= 30, 'hits10': actual['hits'] >= 10,
                  'roi105': actual['roi'] is not None and actual['roi'] >= 1.05,
                  'roi_lower100': actual['roi_95'] is not None and actual['roi_95'][0] > 1}
        assert checks == actual['minimum_checks'] and all(checks.values()) == actual['minimum_checks_passed']


def check_bootstrap(rows, control, group):
    """開催日対応の候補/対照を1抽出ずつ再標本化して区間を検算する。"""
    days = sorted({r['race_date'] for r in rows})
    matrix = []
    for day in days:
        part = [r for r in rows if r['race_date'] == day]
        matrix.append([sum(r['policies']['candidate']['stake'] for r in part), sum(r['policies']['candidate']['payout'] for r in part),
                       sum(r['policies'][control]['payout']-r['policies'][control]['stake'] for r in part), len(part)])
    values = np.asarray(matrix);rng = np.random.default_rng(300)
    totals = np.asarray([values[rng.integers(len(days), size=len(days))].sum(axis=0) for _ in range(2000)])
    valid = totals[:, 0] > 0
    assert int(valid.sum()) == group['policies']['candidate']['roi_valid_draws']
    assert np.allclose(group['policies']['candidate']['roi_95'], np.quantile(totals[valid, 1]/totals[valid, 0], [.025, .975]), atol=1e-10, rtol=0)
    delta = (totals[:, 1]-totals[:, 0]-totals[:, 2])/totals[:, 3]
    assert np.allclose(group['candidate_minus'][control]['profit_difference_per_race_95'], np.quantile(delta, [.025, .975]), atol=1e-10, rtol=0)


def main():
    """診断の元会計と候補の規則、全120会計と代表対応区間、原本/lockを検査する。"""
    rows = json.loads((d.OUT/'rows.json').read_text(encoding='utf-8'))
    diagnosis = json.loads((d.OUT/'diagnosis.json').read_text(encoding='utf-8'))
    ledger = json.loads((d.OUT/'policy-ledger.json').read_text(encoding='utf-8'))
    result = json.loads((d.OUT/'evaluation.json').read_text(encoding='utf-8'))
    lock = json.loads((d.OUT/'candidate-lock.json').read_text(encoding='utf-8'))
    prior = {r['race_key']: r for r in json.loads((d.PRIOR/'ledger.json').read_text(encoding='utf-8'))['V110_common']}
    by_key = {r['race_key']: r for r in rows}
    assert len(by_key) == len(rows) == len(ledger) == 946
    for r in rows:
        p = prior[r['race_key']]
        for c in ('J23', 'V110'):
            for field in ('stake', 'payout', 'loss', 'brier', 'ticket_probability'): near(r['models'][c][field], p['models'][c][field])
        assert r['state'] in d.STATES
        j, v = r['models']['J23'], r['models']['V110']
        state = ('both_same' if j['pair'] == v['pair'] else 'both_different') if j['stake'] and v['stake'] else 'J23_only' if j['stake'] else 'V110_only' if v['stake'] else 'neither'
        assert state == r['state']
        if state == 'both_different': assert not (j['hit'] and v['hit'])
    for scope, periods in diagnosis['scopes'].items():
        for period, stats in periods.items():
            part = independent_subset(rows, scope, period)
            assert len(part) == stats['races']
            for state, g in stats['groups'].items():
                selected = [r for r in part if r['state'] == state]
                assert g['races'] == len(selected)
                for c, a in g['models'].items():
                    stake = sum(r['models'][c]['stake'] for r in selected);payout = sum(r['models'][c]['payout'] for r in selected)
                    assert (a['stake'], a['payout'], a['profit']) == (stake, payout, payout-stake)
                    assert a['hits'] == sum(r['models'][c]['hit'] for r in selected)
    for row in ledger:
        r = by_key[row['race_key']];autumn = int(r['race_date'][5:7]) in [9, 10, 11]
        route = 'V110' if r['course'] == 'tokyo' else 'J23' if autumn else None
        expected = {'J23_all': 'J23', 'V110_all': 'V110', 'J23_autumn': 'J23' if autumn else None,
                    'V110_tokyo': 'V110' if r['course'] == 'tokyo' else None,
                    'route_baseline': route, 'candidate': None if r['course'] == 'tokyo' and r['state'] == 'both_different' else route}
        for name, model in expected.items():
            value = row['policies'][name];assert value['model'] == model
            src = r['models'][model] if model else {'pair': None, 'stake': 0, 'payout': 0}
            for field in ('pair', 'stake', 'payout'): assert value[field] == src[field]
            assert value['stake'] <= 600
        poisoned = {**r, 'winner_pair': [98, 99], 'hr_payout_yen': 999999,
                    'models': {c: {**v, 'payout': 999999, 'hit': True, 'loss': 0} for c,v in r['models'].items()}}
        for name in e.NAMES: assert e.choose(r, name) == e.choose(poisoned, name)
    checks = 0
    for scope, periods in result['scopes'].items():
        for period, group in periods.items():
            part = independent_subset(ledger, scope, period)
            for name, stats in group['policies'].items(): check_stats(part, name, stats);checks += 1
            for name, diff in group['candidate_minus'].items():
                assert diff['profit_difference'] == group['policies']['candidate']['profit']-group['policies'][name]['profit']
    examples = [('both_all', 'all', 'route_baseline'), ('tokyo_all', '2025', 'V110_all'),
                ('tokyo_all', '2026', 'V110_all'), ('tokyo_all', 'all', 'V110_all'), ('tokyo_autumn', 'all', 'V110_all')]
    for scope, period, control in examples:
        check_bootstrap(independent_subset(ledger, scope, period), control, result['scopes'][scope][period])
    assert result['candidate_count'] == 1 and result['adjustments'] == 0 and not result['adoption']
    assert d.sha(d.OUT/'candidate-lock.json') == result['lock_sha256']
    assert d.sha(d.OUT/'diagnosis.json') == lock['diagnosis_sha256'] and d.sha(d.OUT/'rows.json') == lock['rows_sha256']
    assert all(d.sha(d.ROOT/p) == h for p,h in diagnosis['source_sha256'].items())
    protocol = json.loads((d.OUT/'diagnostic-protocol.json').read_text(encoding='utf-8'))
    assert protocol['spec_sha256'] == d.sha(d.ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/300-J23V110買い目重複と単一使い分け検証.md')
    d.save('independent-verification.json', {'status': 'passed', 'source_rows': len(rows), 'summary_checks': checks,
           'bootstrap_checks': len(examples), 'per_race_rule_ignores_outcomes': True, 'five_states_partition': True,
           'source_and_lock_unchanged': True, 'stake_cap': 600, 'adoption': False})
    print(f'independent verification passed: {len(rows)} rows, {checks} summaries, {len(examples)} bootstrap checks')


if __name__ == '__main__': main()
