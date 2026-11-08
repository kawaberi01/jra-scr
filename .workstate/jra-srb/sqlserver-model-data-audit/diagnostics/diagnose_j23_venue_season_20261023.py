"""概要: 保存済みJ23の競馬場・四季別の精度/会計と年をまたぐ再現性を診断する。
作成日: 2026-10-23
入力: spec275、固定30月のJ23/R1/M0/J01保存セルと元指標。
出力: j23_venue_season_20261023へ全54区分・年別/共通月・2024選択lock・レポート。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/diagnose_j23_venue_season_20261023.py
注意事項: 既使用期間の探索のみ。SQL/API・再学習・購入組変更・元run/本番変更なし。
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

import diagnose_j23_saved_errors_20261023 as previous


ROOT, SOURCE = previous.ROOT, previous.SOURCE
sys.path.insert(0, str(ROOT/'scripts'))
from analyze_j23_followup import aggregate

OUT = ROOT/'artifacts/jra_research/j23_venue_season_20261023'
SEASONS = ('春', '夏', '秋', '冬')
VENUES = tuple(previous.COURSES.values())
FAMILIES = {'venue': VENUES, 'season': SEASONS,
            'venue_season': tuple(v+'・'+s for v in VENUES for s in SEASONS)}
YEARS = ('2024', '2025', '2026')


def save(name, value):
    """既存成果物を上書きせず保存し、既存protocolだけは内容一致を検査する。"""
    if name == 'protocol.json' and (OUT/name).exists():
        assert json.loads((OUT/name).read_text(encoding='utf-8')) == json.loads(json.dumps(value))
        return
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def sha(path):
    """元ファイル実内容のSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def season(month):
    """暦月を事前固定した四季へ割り当てる。"""
    assert 1 <= month <= 12
    return '春' if 3 <= month <= 5 else '夏' if 6 <= month <= 8 else '秋' if 9 <= month <= 11 else '冬'


def load():
    """4方式の同一対象とセル/行の整合を検査し、区分metadataを付ける。

    Returns:
        paired行と元ファイル不変検査用SHA。
    Notes:
        保存済み教師と払戻は集計・精算だけに使用する。
    """
    rows, hashes = [], {}
    for path in sorted((SOURCE/'cells').glob('*_J23.json')):
        month = path.name[:7]
        cells = {}
        for case in previous.CASES:
            p = path.parent/(month+'_'+case+'.json')
            c = json.loads(p.read_text(encoding='utf-8-sig'))
            assert hashlib.sha256(previous.canonical({k: v for k, v in c.items() if k != 'cell_sha256'}).encode()).hexdigest() == c['cell_sha256']
            assert c['trained_through'] < month+'-01'
            cells[case] = c
            hashes[str(p.relative_to(ROOT))] = sha(p)
        assert len({c['cohort_sha256'] for c in cells.values()}) == 1
        maps = {case: {r['race_key']: r for r in c['rows']} for case, c in cells.items()}
        assert all(len(maps[case]) == len(cells[case]['rows']) and set(maps[case]) == set(maps['J23']) for case in previous.CASES)
        for key in sorted(maps['J23']):
            r = {case: maps[case][key] for case in previous.CASES}
            for field in ('race_date', 'pair_count', 'winner', 'hr_payout_yen'):
                assert len({a[field] for a in r.values()}) == 1
            for a in r.values():
                assert a['race_date'][:7] == month and 0 < a['winning_probability'] <= 1
                assert abs(a['loss']+math.log(a['winning_probability'])) < 1e-12
                assert abs(a['brier']-(a['squared_sum']-2*a['winning_probability']+1)/a['pair_count']) < 1e-12
                assert abs(a['probability_sum']-1) < 1e-12
                assert a['stake'] in (0, 600)
                assert a['payout'] == (6*a['hr_payout_yen'] if a['stake'] and a['chosen'] == a['winner'] else 0)
            v, s = previous.COURSES[key[8:10]], season(int(month[5:7]))
            rows.append({**r, 'race_key': key, 'race_date': r['J23']['race_date'], 'year': month[:4],
                         'month': month, 'month_number': int(month[5:7]), 'venue': v, 'season': s, 'venue_season': v+'・'+s})
    p = SOURCE/'metrics.json'
    hashes[str(p.relative_to(ROOT))] = sha(p)
    metrics = json.loads(p.read_text(encoding='utf-8-sig'))
    assert len(rows) == len({r['race_key'] for r in rows}) == 7127
    for phase in ('selection', 'confirmation'):
        part = [r for r in rows if (r['month'] <= '2026-03') == (phase == 'selection')]
        for case in previous.CASES:
            a, b = previous.summary([r[case] for r in part]), metrics['phases'][phase][case]
            for field in ('races', 'bets', 'buy_days', 'hits', 'stake', 'payout'):
                assert a[field] == b[field]
            for field in ('logloss', 'brier', 'roi'):
                assert (a[field] is None and b[field] is None) or (a[field] is not None and b[field] is not None and math.isclose(a[field], b[field], abs_tol=1e-12))
    return rows, hashes


def intervals(rows):
    """開催日を単位にROIと同一競走の対照差の探索用95%区間を求める。"""
    if not rows:
        return None
    daily = defaultdict(lambda: np.zeros(6))
    for r in rows:
        j = r['J23']
        daily[r['race_date']] += [j['payout'], j['stake'], 1,
                                  j['loss']-r['M0']['loss'], j['loss']-r['R1']['loss'], j['loss']-r['J01']['loss']]
    values = np.asarray([daily[k] for k in sorted(daily)])
    draws = np.random.default_rng(275).integers(0, len(values), size=(2000, len(values)))
    totals = values[draws].sum(axis=1)
    valid = totals[:, 1] > 0
    bounds = np.quantile(totals[:, 3:]/totals[:, 2, None], [.025, .975], axis=0)
    return {'roi_95': np.quantile(totals[valid, 0]/totals[valid, 1], [.025, .975]).tolist() if valid.any() else None,
            'roi_valid_draws': int(valid.sum()), 'logloss_difference_95': {c: bounds[:, i].tolist() for i, c in enumerate(('M0', 'R1', 'J01'))}}


def summarize(rows, *, bootstrap=False):
    """同一競走の確率精度と元J23購入会計を集計し、空群は評価不能として返す。"""
    bets = [{**r['J23'], 'ev': r['J23']['ticket_probability']*r['J23']['ticket_odds']} for r in rows if r['J23']['stake']]
    account = aggregate(bets)
    largest3 = sum(sorted((r['payout'] for r in bets), reverse=True)[:3])
    account['roi_without_top3'] = (account['payout']-largest3)/account['stake'] if account['stake'] else None
    model_stats = {c: {'logloss': math.fsum(r[c]['loss'] for r in rows)/len(rows) if rows else None,
                       'brier': math.fsum(r[c]['brier'] for r in rows)/len(rows) if rows else None} for c in previous.CASES}
    differences = {c: {'logloss': model_stats['J23']['logloss']-model_stats[c]['logloss'] if rows else None,
                        'brier': model_stats['J23']['brier']-model_stats[c]['brier'] if rows else None} for c in ('M0', 'R1', 'J01')}
    return {'races': len(rows), 'days': len({r['race_date'] for r in rows}), 'account': account,
            'models': model_stats, 'J23_minus': differences, 'months_present': sorted({r['month'] for r in rows}),
            'small_purchase_sample': account['bets'] < 30 or account['buy_days'] < 10 or account['hits'] < 3,
            'intervals_exploratory': intervals(rows) if bootstrap else None}


def grouped(rows, *, bootstrap=False):
    """全10場/4季/40組合せを0件も含めて同じ定義で表示し、合計を検査する。"""
    result = {}
    for family, names in FAMILIES.items():
        result[family] = {n: summarize([r for r in rows if r[family] == n], bootstrap=bootstrap) for n in names}
        assert sum(s['races'] for s in result[family].values()) == len(rows)
        for field in ('bets', 'hits', 'stake', 'payout'):
            assert sum(s['account'][field] for s in result[family].values()) == summarize(rows)['account'][field]
    return result


def eligible(s):
    """2024年だけの保守的な絞り込みscreening条件を満たすかを返す。"""
    a = s['account']
    return a['bets'] >= 100 and a['buy_days'] >= 20 and a['hits'] >= 10 and a['roi'] >= 1.05 and a['roi_without_top3'] > 1


def stable(groups):
    """事前固定した購入件数を満たし3暦年すべて黒字の探索区分を列挙する。"""
    found = {}
    for family, names in FAMILIES.items():
        found[family] = [name for name in names if all(not groups[y][family][name]['small_purchase_sample']
                           and groups[y][family][name]['account']['roi'] > 1 for y in YEARS)]
    return found


def fmt(value, digits=2):
    """比率を百分率へ変換し、未評価をダッシュで表示する。"""
    return '-' if value is None else f'{100*value:.{digits}f}%'


def report(result):
    """全54区分の年別会計と季節構成の制約をMarkdownへ保存する。"""
    lines = ['# J23 競馬場・四季別の再現性診断', '', '2026-10-23。全期間既使用の探索。再学習/独立評価/採用なし。', '',
             '春3〜5月、夏6〜8月、秋9〜11月、冬12〜2月。2024年は4〜12月、2025年は通年、2026年は1〜9月。',
             '以下は元J23の購入を区分したもの。競走0件/購入0件は評価不能であり悪い区分ではない。', '',
             '| 期間 | 競走 | 購入/的中 | ROI | 上位3払戻除外 |', '|---|---:|---:|---:|---:|']
    for y in YEARS:
        s = result['years'][y]['baseline'];a = s['account']
        lines.append(f"| {y} | {s['races']} | {a['bets']}/{a['hits']} | {fmt(a['roi'])} | {fmt(a['roi_without_top3'])} |")
    for family, names in FAMILIES.items():
        lines += ['', f'## {family} 暦年別', '', '| 区分 | 2024 購入/的中・ROI | 2025 購入/的中・ROI | 2026 購入/的中・ROI |', '|---|---:|---:|---:|']
        for name in names:
            cells = []
            for y in YEARS:
                a = result['years'][y]['groups'][family][name]['account']
                cells.append(f"{a['bets']}/{a['hits']}・{fmt(a['roi'])}")
            lines.append('| '+name+' | '+' | '.join(cells)+' |')
    lines += ['', '## 共通4〜9月の季節比較', '', '| 区分 | 2024 | 2025 | 2026 |', '|---|---:|---:|---:|']
    for name in SEASONS:
        cells = []
        for y in YEARS:
            a = result['common_months']['years'][y]['groups']['season'][name]['account']
            cells.append(f"{a['bets']}/{a['hits']}・{fmt(a['roi'])}")
        lines.append('| '+name+' | '+' | '.join(cells)+' |')
    lines += ['', '## 再現性と2024だけで固定した絞り込み', '',
              '30購入/10日/3的中以上かつ3暦年すべてROI>100%の探索区分: '+json.dumps(result['stable_calendar'], ensure_ascii=False),
              '共通4〜9月で同条件: '+json.dumps(result['stable_common_months'], ensure_ascii=False),
              '2024年の100購入/20日/10的中/ROI105%/上位3払戻除外100%超で固定した区分: '+json.dumps(result['selection_lock']['selected'], ensure_ascii=False),
              '', 'このscreeningは実用採用ではない。通過区分が0なら条件を緩めず、政策を作らない。']
    for family, policy in result['locked_policies'].items():
        lines += ['', f'### 固定絞り込み {family}', '', '| 年 | 購入/的中 | ROI | 元全体ROI |', '|---|---:|---:|---:|']
        for y, s in policy['years'].items():
            a = s['account']
            lines.append(f"| {y} | {a['bets']}/{a['hits']} | {fmt(a['roi'])} | {fmt(result['years'][y]['baseline']['account']['roi'])} |")
    lines += ['', '## 精度の読み方と限界', '',
              '全区分の対市場/R1/J01のlogloss/Brier差、日単位探索95%区間、元選抜/既使用確認の比較はresults.jsonへ保存。',
              '異なる競馬場間の生loglossは頭数/市場難度も異なるため順位だけで得意と判定しない。',
              '競馬場と季節は開催日程によって結び付き、独立な要因ではない。0件から未開催/欠測を断定しない。',
              '共通月比較も同じ開催条件/頭数を完全に揃えた因果比較ではない。夏除外は買わない期間を作る政策で、モデル精度の改善ではない。',
              '区分・信頼区間・3年黒字の抽出は多重探索。未知データの有意性/採用根拠としない。',
              '2024だけの選択でも研究計画は全期間を見た後。独立新期間の発走前保存検証が必要。',
              '元原本不変・同一競走/会計/元phase一致。SQL/API0、モデル学習0、本番変更0。']
    with (OUT/'report.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(lines)+'\n')


def main():
    """protocolを先に固定し、年別診断と2024だけの絞り込みを保存する。"""
    OUT.mkdir(exist_ok=True)
    assert [season(m) for m in range(1, 13)] == ['冬', '冬', '春', '春', '春', '夏', '夏', '夏', '秋', '秋', '秋', '冬']
    spec = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/275-J23競馬場季節別の再現性診断.md'
    save('protocol.json', {'spec_sha256': sha(spec), 'families': FAMILIES, 'season_months': {'春': [3, 4, 5], '夏': [6, 7, 8], '秋': [9, 10, 11], '冬': [12, 1, 2]},
                           'calendar_years': YEARS, 'common_months': [4, 5, 6, 7, 8, 9], 'bootstrap': {'draws': 2000, 'seed': 275, 'multiple_comparison_adjusted': False},
                           'screening_2024': {'min_bets': 100, 'min_days': 20, 'min_hits': 10, 'min_roi': 1.05, 'roi_without_top3_strictly_above': 1},
                           'independent_test': False, 'adoption': False})
    rows, hashes = load()
    years = {y: {'baseline': summarize([r for r in rows if r['year'] == y], bootstrap=True),
                  'groups': grouped([r for r in rows if r['year'] == y])} for y in YEARS}
    selected = {family: [name for name in names if eligible(years['2024']['groups'][family][name])] for family, names in FAMILIES.items()}
    lock = {'selected': selected, 'selection_year': '2024', 'selection_cohort_sha256': hashlib.sha256(previous.canonical([r['race_key'] for r in rows if r['year'] == '2024']).encode()).hexdigest(),
            'selection_max_date': max(r['race_date'] for r in rows if r['year'] == '2024'), 'selection_criteria_changed': False}
    save('selection-lock.json', lock)
    common = [r for r in rows if r['month_number'] in (4, 5, 6, 7, 8, 9)]
    common_years = {y: {'baseline': summarize([r for r in common if r['year'] == y]),
                         'groups': grouped([r for r in common if r['year'] == y])} for y in YEARS}
    assert all({r['month_number'] for r in common if r['year'] == y} == {4, 5, 6, 7, 8, 9} for y in YEARS)
    phases = {}
    for phase in ('selection', 'confirmation_already_seen'):
        part = [r for r in rows if (r['month'] <= '2026-03') == (phase == 'selection')]
        phases[phase] = {'baseline': summarize(part, bootstrap=True), 'groups': grouped(part, bootstrap=True)}
    policies = {}
    for family, names in selected.items():
        if names:
            policies[family] = {'selected': names, 'years': {y: summarize([r for r in rows if r['year'] == y and r[family] in names], bootstrap=True) for y in YEARS}}
    result = {'years': years, 'common_months': {'months': [4, 5, 6, 7, 8, 9], 'years': common_years},
              'phases': phases, 'selection_lock': lock, 'locked_policies': policies,
              'stable_calendar': stable({y: years[y]['groups'] for y in YEARS}),
              'stable_common_months': stable({y: common_years[y]['groups'] for y in YEARS}),
              'verification': {'status': 'passed', 'races': len(rows), 'source_sha256': hashes,
                               'source_unchanged': True, 'same_race_comparison': True, 'model_fits': 0,
                               'sql_queries': 0, 'api_requests': 0, 'independent_test': False, 'adoption': False}}
    assert all(sha(ROOT/p) == h for p, h in hashes.items())
    save('results.json', result)
    report(result)
    print(json.dumps({'years': {y: years[y]['baseline']['account'] for y in YEARS}, 'stable_calendar': result['stable_calendar'],
                      'stable_common_months': result['stable_common_months'], 'selected_2024': selected}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
