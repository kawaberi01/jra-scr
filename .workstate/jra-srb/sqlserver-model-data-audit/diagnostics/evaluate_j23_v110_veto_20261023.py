"""概要: 診断後に固定した東京不一致見送り・中山秋J23の1案を同一予算上限で比較する。
作成日: 2026-10-23
入力: spec300、diagnosis/rows、事前candidate-lock.json。
出力: j23_v110_complementarity_20261023のpolicy-ledger・比較結果・レポート。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/evaluate_j23_v110_veto_20261023.py
注意事項: 結果既使用の探索1案。確率モデル学習・SQL/API・実購入・本番変更なし。
"""

from collections import defaultdict
import json

import numpy as np

import diagnose_j23_v110_overlap_20261023 as d


OUT = d.OUT
NAMES = ('J23_all', 'V110_all', 'J23_autumn', 'V110_tokyo', 'route_baseline', 'candidate')
SCOPES = ('both_all', 'tokyo_all', 'tokyo_autumn', 'nakayama_autumn')


def choose(row, name):
    """結果/払戻を使わず、元モデルの購入状態と場/月だけで採用元を決める。"""
    autumn = 9 <= int(row['race_date'][5:7]) <= 11
    if name == 'J23_all': return 'J23'
    if name == 'V110_all': return 'V110'
    if name == 'J23_autumn': return 'J23' if autumn else None
    if name == 'V110_tokyo': return 'V110' if row['course'] == 'tokyo' else None
    if row['course'] == 'tokyo':
        if name == 'candidate' and row['state'] == 'both_different': return None
        return 'V110'
    return 'J23' if autumn else None


def build(rows):
    """元選択の部分集合だけで6構成の会計行を作り、各競走上限600円を検査する。"""
    ledger = []
    for r in rows:
        policies = {}
        for name in NAMES:
            model = choose(r, name)
            source = r['models'][model] if model else None
            value = {'model': model, 'pair': source['pair'] if source else None,
                     'stake': source['stake'] if source else 0, 'payout': source['payout'] if source else 0}
            assert value['stake'] in (0, 600) and (value['stake'] > 0) == (value['pair'] is not None)
            assert value['payout'] == (6*r['hr_payout_yen'] if value['pair'] == r['winner_pair'] else 0)
            policies[name] = value
        # 東京不一致以外は既存の場別使い分けと完全に同じ。
        if r['course'] != 'tokyo' or r['state'] != 'both_different':
            assert policies['candidate'] == policies['route_baseline']
        ledger.append({'race_key': r['race_key'], 'race_date': r['race_date'], 'course': r['course'], 'policies': policies})
    return ledger


def summary(rows, name):
    """支出の違いを隠さず、会計・日末DD・高配当依存を集計する。"""
    values = [r['policies'][name] for r in rows]
    bets = [v for v in values if v['stake']]
    stake = sum(v['stake'] for v in values);payout = sum(v['payout'] for v in values)
    days = defaultdict(lambda: [0, 0])
    for r in rows:
        v = r['policies'][name];days[r['race_date']][0] += v['payout']-v['stake'];days[r['race_date']][1] += v['stake']
    equity = np.cumsum([0]+[v[0] for _,v in sorted(days.items())])
    top = sorted((v['payout'] for v in bets), reverse=True)
    return {'races': len(rows), 'days': len(days), 'bets': len(bets), 'hits': sum(v['payout'] > 0 for v in bets),
            'buy_days': sum(v[1] > 0 for v in days.values()), 'stake': stake, 'payout': payout, 'profit': payout-stake,
            'roi': payout/stake if stake else None, 'profit_per_race': (payout-stake)/len(rows) if rows else None,
            'bet_coverage': len(bets)/len(rows) if rows else None,
            'roi_without_largest': (payout-sum(top[:1]))/stake if stake else None,
            'roi_without_top3': (payout-sum(top[:3]))/stake if stake else None,
            'max_drawdown_daily': int(np.max(np.maximum.accumulate(equity)-equity)),
            'worst_day_profit': min((v[0] for v in days.values()), default=None)}


def compare(rows):
    """日単位の対応bootstrapで候補と各対照の利益差とROI区間を求める。"""
    stats = {name: summary(rows, name) for name in NAMES}
    if not rows: return {'races': 0, 'policies': stats, 'candidate_minus': {}}
    days = sorted({r['race_date'] for r in rows})
    samples = np.random.default_rng(300).integers(0, len(days), size=(2000, len(days)))
    totals = {}
    for name in NAMES:
        daily = defaultdict(lambda: np.zeros(3))
        for r in rows:
            v = r['policies'][name];daily[r['race_date']] += [v['stake'], v['payout'], 1]
        summed = np.asarray([daily[day] for day in days])[samples].sum(axis=1);totals[name] = summed
        valid = summed[:, 0] > 0
        s = stats[name]
        s['roi_95'] = np.quantile(summed[valid, 1]/summed[valid, 0], [.025, .975]).tolist() if valid.any() else None
        s['roi_valid_draws'] = int(valid.sum())
        s['minimum_checks'] = {'bets100': s['bets'] >= 100, 'days30': s['buy_days'] >= 30, 'hits10': s['hits'] >= 10,
                               'roi105': s['roi'] is not None and s['roi'] >= 1.05,
                               'roi_lower100': s['roi_95'] is not None and s['roi_95'][0] > 1}
        s['minimum_checks_passed'] = all(s['minimum_checks'].values())
    differences = {}
    c = totals['candidate']
    for control in NAMES[:-1]:
        v = totals[control]
        deltas = ((c[:, 1]-c[:, 0])-(v[:, 1]-v[:, 0]))/c[:, 2]
        differences[control] = {'profit_difference': stats['candidate']['profit']-stats[control]['profit'],
                                'profit_difference_per_race': stats['candidate']['profit_per_race']-stats[control]['profit_per_race'],
                                'profit_difference_per_race_95': np.quantile(deltas, [.025, .975]).tolist()}
    return {'races': len(rows), 'policies': stats, 'candidate_minus': differences}


def scope_rows(rows, scope, period):
    """場/秋/期間の固定区分だけを抽出する。"""
    return [r for r in rows if (not scope.startswith('tokyo') or r['course'] == 'tokyo')
            and (not scope.startswith('nakayama') or r['course'] == 'nakayama')
            and ('autumn' not in scope or 9 <= int(r['race_date'][5:7]) <= 11)
            and (period == 'all' or period == 'through_2025' and r['race_date'] < '2026-01-01' or r['race_date'][:4] == period)]


def main():
    """固定lockを検査し1案だけ評価して、条件を変えず全比較を保存する。"""
    lock_path = OUT/'candidate-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    assert lock['candidate_count'] == 1 and lock['rule'] == 'tokyo_V110_veto_J23_disagreement_nakayama_autumn_J23'
    assert d.sha(OUT/'diagnosis.json') == lock['diagnosis_sha256'] and d.sha(OUT/'rows.json') == lock['rows_sha256']
    assert lock['controls'] == list(NAMES[:-1]) and lock['scopes'] == list(SCOPES)
    before = d.sha(lock_path)
    rows = json.loads((OUT/'rows.json').read_text(encoding='utf-8'))
    ledger = build(rows)
    result = {scope: {p: compare(scope_rows(ledger, scope, p)) for p in d.PERIODS} for scope in SCOPES}
    sources = json.loads((OUT/'diagnosis.json').read_text(encoding='utf-8'))['source_sha256']
    assert before == d.sha(lock_path) and all(d.sha(d.ROOT/p) == h for p,h in sources.items())
    d.save('policy-ledger.json', ledger)
    d.save('evaluation.json', {'lock_sha256': before, 'scopes': result, 'candidate_count': 1, 'adjustments': 0,
                              'adoption': False, 'new_fits': 0, 'sql_api_requests': 0, 'source_unchanged': True})
    print(json.dumps({scope: {p: {'candidate': values['policies']['candidate'], 'differences': values['candidate_minus']}
                              for p,values in periods.items()} for scope,periods in result.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
