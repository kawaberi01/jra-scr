"""概要: 保存済みJ23・R1・市場・J01の同一競走誤差を探索的に診断する。
作成日: 2026-10-23
入力: 固定30仮説runの4方式120セル、事前固定protocol.json。
出力: artifacts/jra_research/j23_error_diagnosis_20261023の診断JSONとMarkdown。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/diagnose_j23_saved_errors_20261023.py
注意事項: 既使用期間の探索。SQL・学習・モデル変更・元run更新なし。新規成果物のみ保存する。
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
OUT = ROOT/'artifacts/jra_research/j23_error_diagnosis_20261023'
CASES = ('J23', 'R1', 'M0', 'J01')
COURSES = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
           '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}


def canonical(value):
    """既存研究のcell SHAと同じcanonical表現を返す。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def save(name, value):
    """既存成果物を上書きせず、有限JSONをUTF-8で新規保存する。"""
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def digest(path):
    """実ファイル内容のSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(rows):
    """保存行から確率損失、購入会計、購入分限定の校正を再計算する。"""
    bets = [r for r in rows if r['stake']]
    stake = sum(r['stake'] for r in bets)
    payout = sum(r['payout'] for r in bets)
    expected = sum(r['ticket_probability'] for r in bets)
    hits = sum(r['chosen'] == r['winner'] for r in bets)
    return {'races': len(rows), 'days': len({r['race_date'] for r in rows}),
            'logloss': float(np.mean([r['loss'] for r in rows])),
            'brier': float(np.mean([r['brier'] for r in rows])),
            'bets': len(bets), 'buy_days': len({r['race_date'] for r in bets}), 'hits': hits,
            'expected_hits': expected, 'observed_to_expected_hits': hits/expected if expected else None,
            'stake': stake, 'payout': payout, 'roi': payout/stake if stake else None,
            'roi_without_largest': (payout-max((r['payout'] for r in bets), default=0))/stake if stake else None}


def comparison(paired):
    """同一開催日単位の対応差と探索用95%区間を3対照について求める。"""
    stats = {case: summary([r[case] for r in paired]) for case in CASES}
    differences = {}
    for control in ('R1', 'M0', 'J01'):
        daily = defaultdict(lambda: np.zeros(3))
        for row in paired:
            a, b = row['J23'], row[control]
            daily[a['race_date']] += [a['loss']-b['loss'], a['brier']-b['brier'], 1]
        values = np.asarray([v for _, v in sorted(daily.items())])
        rng = np.random.default_rng(259)
        draws = rng.integers(0, len(values), size=(2000, len(values)))
        totals = values[draws].sum(axis=1)
        deltas = totals[:, :2]/totals[:, 2, None]
        bounds = np.quantile(deltas, [.025, .975], axis=0)
        differences[control] = {'logloss_difference': stats['J23']['logloss']-stats[control]['logloss'],
                                'relative_logloss_gain': 1-stats['J23']['logloss']/stats[control]['logloss'],
                                'brier_difference': stats['J23']['brier']-stats[control]['brier'],
                                'logloss_difference_95': bounds[:, 0].tolist(),
                                'brier_difference_95': bounds[:, 1].tolist(),
                                'fraction_races_J23_lower_loss': sum(r['J23']['loss'] < r[control]['loss'] for r in paired)/len(paired)}
    return {'small_group': stats['J23']['races'] < 100 or stats['J23']['days'] < 10,
            'models': stats, 'J23_minus': differences}


def purchase_groups(rows, field, edges):
    """購入済みの確率/価格を固定境界で区分し、部分集合だけの校正を返す。"""
    groups = {}
    for low, high in zip(edges, edges[1:]):
        selected = [r for r in rows if r['stake'] and low <= r[field] < high]
        if selected:
            groups[f'[{low},{high})'] = summary(selected)
    assert sum(v['bets'] for v in groups.values()) == sum(bool(r['stake']) for r in rows)
    return groups


def main():
    """固定済みの区分だけを診断し、原本・会計・損失の整合確認後に結果を保存する。"""
    protocol = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    assert protocol['comparators'] == list(CASES) and protocol['training_runs'] == 0
    paths = [p for case in CASES for p in sorted((SOURCE/'cells').glob('*_'+case+'.json'))]
    paths += [SOURCE/'metrics.json', SOURCE/'frozen.json', SOURCE/'manifest.json']
    before = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    cells, grouped = {}, defaultdict(dict)
    for path in paths[:-3]:
        cell = json.loads(path.read_text(encoding='utf-8-sig'))
        assert hashlib.sha256(canonical({k: v for k, v in cell.items() if k != 'cell_sha256'}).encode()).hexdigest() == cell['cell_sha256']
        assert cell['status'] == 'evaluated' and cell['trained_through'] < cell['month']+'-01'
        assert len({r['race_key'] for r in cell['rows']}) == len(cell['rows'])
        for r in cell['rows']:
            assert math.isclose(r['loss'], -math.log(r['winning_probability']), abs_tol=1e-12)
            assert math.isclose(r['brier'], (r['squared_sum']-2*r['winning_probability']+1)/r['pair_count'], abs_tol=1e-14)
            assert r['stake'] in (0, 600) and r['payout'] == (r['hr_payout_yen']*6 if r['stake'] and r['chosen'] == r['winner'] else 0)
            assert math.isclose(r['probability_sum'], 1, abs_tol=1e-9)
        grouped[cell['month']][cell['case']] = cell
        cells[(cell['month'], cell['case'])] = cell
    assert len(cells) == 120 and len(grouped) == 30
    phases = defaultdict(list)
    for month, cases in sorted(grouped.items()):
        assert set(cases) == set(CASES)
        maps = {c: {r['race_key']: r for r in v['rows']} for c, v in cases.items()}
        assert all(set(maps[c]) == set(maps['J23']) for c in CASES)
        assert len({v['cohort_sha256'] for v in cases.values()}) == 1
        for key in sorted(maps['J23']):
            pair = {c: maps[c][key] for c in CASES}
            for field in ('race_date', 'pair_count', 'winner', 'hr_payout_yen'):
                assert len({r[field] for r in pair.values()}) == 1
            a = pair['J23']
            n = int((1+math.isqrt(1+8*a['pair_count']))//2)
            assert n*(n-1)//2 == a['pair_count'] and 8 <= n <= 18
            assert a['race_date'][:7] == month
            pair['month'] = month
            pair['venue'] = COURSES[key[8:10]]
            pair['field_size'] = '8-11' if n <= 11 else '12-14' if n <= 14 else '15-18'
            pair['buy_status'] = 'buy' if a['stake'] else 'no_buy'
            phases['selection' if month <= '2026-03' else 'confirmation_already_seen'].append(pair)
    original = json.loads((SOURCE/'metrics.json').read_text(encoding='utf-8-sig'))
    results = {'protocol': protocol, 'phases': {}}
    for phase, paired in phases.items():
        result = comparison(paired)
        phase_key = 'confirmation' if phase == 'confirmation_already_seen' else phase
        for case in CASES:
            ref, actual = original['phases'][phase_key][case], result['models'][case]
            for field in ('races', 'bets', 'buy_days', 'hits', 'stake', 'payout'):
                assert ref[field] == actual[field]
            for field in ('logloss', 'brier', 'roi'):
                assert (ref[field] is None and actual[field] is None) or math.isclose(ref[field], actual[field], rel_tol=1e-12, abs_tol=1e-14)
        result['groups'] = {}
        for field in ('month', 'venue', 'field_size', 'buy_status'):
            values = defaultdict(list)
            for row in paired:
                values[row[field]].append(row)
            result['groups'][field] = {name: comparison(rows) for name, rows in sorted(values.items())}
            assert sum(v['models']['J23']['races'] for v in result['groups'][field].values()) == len(paired)
        result['purchase_calibration'] = {}
        for case in CASES:
            rows = [r[case] for r in paired]
            result['purchase_calibration'][case] = {
                'probability': purchase_groups(rows, 'ticket_probability', [0, .02, .05, .1, .2, 1.000001]),
                'odds': purchase_groups(rows, 'ticket_odds', [0, 10, 30, 1e300])}
        results['phases'][phase] = result
    assert before == {str(p.relative_to(ROOT)): digest(p) for p in paths}
    results['verification'] = {'status': 'passed', 'aligned_cells': len(cells),
                               'races': sum(len(v) for v in phases.values()), 'original_summaries_match': True,
                               'row_logloss_brier_accounting_match': True, 'source_unchanged': True,
                               'source_sha256': before, 'sql_queries': 0, 'training_runs': 0,
                               'new_model_candidates': 0, 'independent_test': False}
    save('results.json', results)
    lines = ['# J23保存済み予測の誤差診断', '', '2026-10-23。既使用期間の探索診断。新学習・独立評価・採用判断なし。', '',
             '差はJ23−対照。負ならJ23の誤差が小さい。区間は開催日単位2,000回の探索用95%区間で、多重比較補正なし。', '']
    for phase, result in results['phases'].items():
        lines += [f'## {phase}', '', '| 方式 | 競走 | logloss | Brier | 購入 | 期待的中/実的中 | ROI |', '|---|---:|---:|---:|---:|---:|---:|']
        for c, s in result['models'].items():
            roi = f"{s['roi']*100:.2f}%" if s['roi'] is not None else '購入なし'
            lines.append(f"| {c} | {s['races']} | {s['logloss']:.8f} | {s['brier']:.8f} | {s['bets']} | {s['expected_hits']:.2f}/{s['hits']} | {roi} |")
        lines += ['', '| 対照 | logloss差 | 相対改善 | 差95%区間 |', '|---|---:|---:|---|']
        for c, d in result['J23_minus'].items():
            lines.append(f"| {c} | {d['logloss_difference']:.8f} | {100*d['relative_logloss_gain']:.4f}% | {d['logloss_difference_95']} |")
        for field, groups in result['groups'].items():
            lines += ['', f'### {field}', '', '| 区分 | 競走/日 | 対R1差 | 対市場差 | 対J01差 | 小標本 |', '|---|---:|---:|---:|---:|---|']
            for name, group in groups.items():
                s, d = group['models']['J23'], group['J23_minus']
                lines.append(f"| {name} | {s['races']}/{s['days']} | {d['R1']['logloss_difference']:.6f} | {d['M0']['logloss_difference']:.6f} | {d['J01']['logloss_difference']:.6f} | {group['small_group']} |")
        lines += ['', '### J23購入分の確率整合', '', '| 確率帯 | 購入 | 期待的中 | 実的中 | 実/期待 |', '|---|---:|---:|---:|---:|']
        for name, s in result['purchase_calibration']['J23']['probability'].items():
            lines.append(f"| {name} | {s['bets']} | {s['expected_hits']:.2f} | {s['hits']} | {s['observed_to_expected_hits']:.4f} |")
    lines += ['', '## 限界', '',
              '- 全馬連の確率ベクトルが保存されていないため、未選択ペア全体の校正、モデル混合、同一購入ペアの対照確率は復元していない。',
              '- 時計/信頼度/PL乖離そのものは行にない。悪化する区分と因果的な特徴原因を同一視しない。',
              '- 確認6月も既使用。区分・区間は探索であり、新候補の独立採用根拠にしない。',
              '- 元120セル/指標/凍結/manifestのSHA不変、元phase指標と会計・行ごとの損失再計算を照合passed。',
              '- SQL0・学習0・新規モデル候補0。購入閾値変更0。']
    with (OUT/'report.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(lines)+'\n')
    print('\n'.join(lines[:21]))
    print('verification passed:', results['verification']['races'], 'races;', OUT)


if __name__ == '__main__':
    main()
