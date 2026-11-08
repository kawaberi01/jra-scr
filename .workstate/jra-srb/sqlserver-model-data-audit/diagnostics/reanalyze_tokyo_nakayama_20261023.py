"""概要: 東京・中山向けにJ23/R1/V110/S08の保存OOSを同一競走で固定再分析する。
作成日: 2026-10-23
入力: spec295、元30月セル、V110保存買い目/分布、S08分解metrics/選択行。
出力: tokyo_nakayama_reanalysis_20261023のprotocol・ledger・整合診断・全条件年別結果。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/reanalyze_tokyo_nakayama_20261023.py
注意事項: 既使用期間の探索。SQL/API・学習・元run更新・本番変更なし。予算は600円へ比例換算。
"""

from collections import Counter, defaultdict
import gzip
from itertools import combinations
import json
import math
from pathlib import Path

import numpy as np

import diagnose_j23_venue_season_20261023 as base


ROOT, OUT = base.ROOT, base.ROOT/'artifacts/jra_research/tokyo_nakayama_reanalysis_20261023'
VROOT = ROOT/'.workstate/jra-srb/jra-second-ten-nosummer-v1'
SROOT = ROOT/'artifacts/jra_research/runs/20261017T091533Z_631037c77cb34fd895c779df1ba77e8d'
SCOPES = ('both_all', 'tokyo_all', 'nakayama_all', 'both_autumn', 'tokyo_autumn', 'nakayama_autumn')
PERIODS = ('2024', '2025', '2026', 'through_2025', 'all')


def save(name, value):
    """既存成果物を上書きせず有限JSONを新規保存する。"""
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def native(row):
    """元セルの確率指標/購入会計を比較用の最小行へ変換する。"""
    return {k: row[k] for k in ('loss', 'brier', 'stake', 'payout', 'ticket_probability')}


def v110_panel(source, hashes):
    """V110分布・元loss・元購入精算を共通キーと照合し、不整合を理由別に隔離する。

    Returns:
        共通行panelと、ラベル/数値市場の一致・除外記録。
    Notes:
        保存値を検査する限定照合で、全馬名/horse ID/公表時点の証明ではない。
    """
    ticket_path, pred_path = VROOT/'V110_tickets.json', VROOT/'predictions.jsonl.gz'
    hashes.update({str(p.relative_to(ROOT)): base.sha(p) for p in (ticket_path, pred_path, VROOT/'protocol.json')})
    original = json.loads(ticket_path.read_text(encoding='utf-8-sig'))
    meta = {r['race_id']: r for part in ('development', 'exploratory') for r in original[part]}
    assert len(meta) == 2704
    accepted, rejected, price_checks = [], [], Counter()
    seen = set()
    with gzip.open(pred_path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            d = json.loads(line)
            key = d['race_id']
            if d['trial'] != 'V110' or key not in source or key not in meta:
                continue
            assert key not in seen
            seen.add(key)
            m, b = meta[key], source[key]
            p, projected = np.asarray(d['probability']), np.asarray(d['projected_return'])
            keys = [tuple(map(int, str(k).split('-'))) for k in d['keys']]
            numbers = sorted({n for pair in keys for n in pair})
            winner = b['raw']['J23']['winner']
            reason = None
            if d['race_date'] != b['race_date'] or m['course'] != b['course']:
                reason = 'date_or_course'
            elif keys != list(combinations(numbers, 2)) or len(p) != b['raw']['J23']['pair_count']:
                reason = 'pair_roster_or_count'
            elif not np.isfinite(p).all() or not np.all(p > 0) or abs(p.sum()-1) > 1e-10:
                reason = 'probability'
            elif abs(-math.log(p[winner])-m['loss']) > 1e-9:
                reason = 'winning_index_or_saved_loss'
            if reason:
                rejected.append({'race_key': key, 'reason': reason})
                continue
            ticket = m['ticket']
            if ticket:
                ti = keys.index(tuple(map(int, ticket['key'].split('-'))))
                assert ti == ticket['index'] and abs(p[ti]-ticket['probability']) < 1e-12
                assert ticket['payout'] == (b['raw']['J23']['hr_payout_yen'] if ti == winner else 0)
                assert abs(projected[ti]-ticket['projected_return']) < 1e-10
            prices = projected/p
            assert np.isfinite(prices).all() and np.all(prices >= 1)
            q = 1/prices;q /= q.sum()
            market = b['raw']['M0']
            price_checks['same_market_winner_and_moment' if abs(q[winner]-market['winning_probability']) < 1e-10 and abs(float(q@q)-market['squared_sum']) < 1e-10 else 'different_market_numeric'] += 1
            if ticket:
                assert abs(prices[ti]-ticket['odds_t30']) < 1e-8
            chosen = b['raw']['J23']['chosen']
            if chosen is not None:
                price_checks['same_J23_selected_quote' if abs(prices[chosen]-b['raw']['J23']['ticket_odds']) < 1e-8 else 'different_J23_selected_quote'] += 1
            accepted.append({**b['public'], 'distance': m['distance'], 'surface': m['surface'],
                             'models': {**b['models'], 'V110': {'loss': float(-np.log(p[winner])),
                                'brier': float((p@p-2*p[winner]+1)/len(p)), 'stake': 600 if ticket else 0,
                                'payout': 6*ticket['payout'] if ticket else 0,
                                'ticket_probability': float(ticket['probability']) if ticket else None}}})
    assert seen == (set(meta) & set(source))
    return accepted, {'matched_ids': len(seen), 'accepted': len(accepted), 'rejected': rejected,
                      'numeric_price_checks': dict(price_checks), 'full_horse_identity_and_publication_time_proven': False}


def s08_panel(source, hashes):
    """S08競走全体指標・内容観測群・選択行を照合し、共通競走の元政策を集める。"""
    metrics_path, pred_path = SROOT/'metrics.json', SROOT/'predictions.jsonl.gz'
    hashes.update({str(p.relative_to(ROOT)): base.sha(p) for p in (metrics_path, pred_path)})
    metrics = json.loads(metrics_path.read_text(encoding='utf-8-sig'))
    diagnostics = {r['race_key']: r for r in metrics['race_diagnostics']}
    saved = {}
    with gzip.open(pred_path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            r = json.loads(line)
            if r['variant'] in ('full', 'history'):
                token = (r['race_key'], r['variant'])
                assert token not in saved
                saved[token] = r
    accepted = []
    for key in sorted(set(diagnostics) & set(source)):
        d, b = diagnostics[key], source[key]
        assert d['race_date'] == b['race_date']
        assert d['stratum'] == ('rich' if d['corner_pair_observed'] >= .5 and d['pace_pair_observed'] >= .5 else 'sparse')
        extra = {}
        for variant, case in (('full', 'S08'), ('history', 'S08_history')):
            r = saved[(key, variant)]
            assert len(d['tickets'][variant]) == 1
            t = d['tickets'][variant][0]
            assert sorted(map(int, t['horses'])) == sorted(map(int, r['horses']))
            assert t['stake_yen'] == r['ticket']['stake_yen'] == 600
            assert t['payout_yen'] == r['ticket']['payout_yen'] == (6*b['raw']['J23']['hr_payout_yen'] if r['target'] else 0)
            extra[case] = {'loss': d['logloss'][variant], 'brier': d['brier'][variant], 'stake': 600,
                           'payout': t['payout_yen'], 'ticket_probability': r['probability']}
        accepted.append({**b['public'], 'stratum': d['stratum'], 'models': {**b['models'], **extra}})
    return accepted, {'native_races': len(diagnostics), 'common_races': len(accepted),
                      'race_level_full_loss_and_brier_available': True, 'price_and_full_horse_identity_proven': False}


def summary(rows, case):
    """同一競走の全確率指標と600円基準の元政策の会計/脆弱性を集計する。"""
    values = [r['models'][case] for r in rows]
    bets = [v for v in values if v['stake']]
    stake, payout = sum(v['stake'] for v in bets), sum(v['payout'] for v in bets)
    profit = high = dd = 0
    for r in sorted(rows, key=lambda r: r['race_key']):
        v = r['models'][case];profit += v['payout']-v['stake'];high = max(high, profit);dd = max(dd, high-profit)
    largest = sorted((v['payout'] for v in bets), reverse=True)
    result = {'races': len(rows), 'days': len({r['race_date'] for r in rows}),
              'months': sorted({r['race_date'][:7] for r in rows}),
              'logloss': math.fsum(v['loss'] for v in values)/len(values) if values else None,
              'brier': math.fsum(v['brier'] for v in values)/len(values) if values else None,
              'bets': len(bets), 'buy_days': len({r['race_date'] for r in rows if r['models'][case]['stake']}),
              'hits': sum(v['payout'] > 0 for v in bets), 'stake': stake, 'payout': payout, 'profit': payout-stake,
              'profit_per_race': (payout-stake)/len(rows) if rows else None,
              'expected_hits': math.fsum(v['ticket_probability'] for v in bets),
              'roi': payout/stake if stake else None, 'roi_without_largest': (payout-sum(largest[:1]))/stake if stake else None,
              'roi_without_top3': (payout-sum(largest[:3]))/stake if stake else None, 'max_drawdown': dd}
    return result


def compare(rows):
    """同じ開催日の対応再標本化で、元政策とJ23の損失/利益差を比較する。"""
    if not rows:
        return {'races': 0, 'models': {}}
    cases = list(rows[0]['models'])
    stats = {c: summary(rows, c) for c in cases}
    days = sorted({r['race_date'] for r in rows})
    for case in cases:
        daily = defaultdict(lambda: np.zeros(6))
        for r in rows:
            v, j = r['models'][case], r['models']['J23']
            daily[r['race_date']] += [v['payout'], v['stake'], 1, v['loss']-j['loss'],
                                      v['payout']-v['stake']-j['payout']+j['stake'], v['brier']-j['brier']]
        values = np.asarray([daily[d] for d in days])
        draws = np.random.default_rng(295).integers(0, len(days), size=(2000, len(days)))
        totals = values[draws].sum(axis=1);valid = totals[:, 1] > 0
        s = stats[case]
        s['roi_95'] = np.quantile(totals[valid, 0]/totals[valid, 1], [.025, .975]).tolist() if valid.any() else None
        s['roi_valid_draws'] = int(valid.sum())
        s['loss_difference_vs_J23'] = s['logloss']-stats['J23']['logloss']
        s['loss_difference_95'] = np.quantile(totals[:, 3]/totals[:, 2], [.025, .975]).tolist()
        s['profit_difference_per_race'] = s['profit_per_race']-stats['J23']['profit_per_race']
        s['profit_difference_per_race_95'] = np.quantile(totals[:, 4]/totals[:, 2], [.025, .975]).tolist()
        s['brier_difference_95'] = np.quantile(totals[:, 5]/totals[:, 2], [.025, .975]).tolist()
        checks = {'min_bets': s['bets'] >= 100, 'min_days': s['buy_days'] >= 30, 'min_hits': s['hits'] >= 10,
                  'roi105': s['roi'] is not None and s['roi'] >= 1.05,
                  'roi_lower_above100': s['roi_95'] is not None and s['roi_95'][0] > 1}
        s['minimum_purchase_checks'] = checks
        s['minimum_purchase_checks_passed'] = all(checks.values())
    return {'races': len(rows), 'models': stats}


def subset(rows, scope, period):
    """結果を参照せず事前固定した場/秋/距離/観測群/年を抽出する。"""
    selected = []
    for r in rows:
        if scope.startswith('tokyo') and r['course'] != 'tokyo' or scope.startswith('nakayama') and r['course'] != 'nakayama':
            continue
        if 'autumn' in scope and int(r['race_date'][5:7]) not in (9, 10, 11):
            continue
        if 'long' in scope and r.get('distance', 0) <= 2000:
            continue
        if scope.endswith('_rich') and r.get('stratum') != 'rich' or scope.endswith('_sparse') and r.get('stratum') != 'sparse':
            continue
        if period in ('2024', '2025', '2026') and not r['race_date'].startswith(period):
            continue
        if period == 'through_2025' and r['race_date'] >= '2026-01-01':
            continue
        selected.append(r)
    return selected


def render(results):
    """モデルごとの年別購入/収益と同一対象の精度をMarkdownで示す。"""
    lines = ['# 東京・中山向け保存研究の再分析', '', '2026-10-23。2026-09までの既使用OOS。各panel内で同一競走、元政策を600円換算。',
             '異なるpanelの件数/時点価格/入力が違うためROIを直接順位付けしない。', '']
    for panel, scopes in results['panels'].items():
        lines += [f'## {panel}', '']
        for scope, periods in scopes.items():
            cases = list(periods['all']['models'])
            lines += [f'### {scope}', '', '| モデル | 2024 購入/的中 ROI | 2025 購入/的中 ROI | 2026 購入/的中 ROI | 全競走loss |', '|---|---:|---:|---:|---:|']
            for c in cases:
                cells = []
                for y in ('2024', '2025', '2026'):
                    s = periods[y]['models'].get(c)
                    cells.append('-' if s is None else f"{s['bets']}/{s['hits']} {base.fmt(s['roi'])}")
                lines.append('| '+c+' | '+' | '.join(cells)+f" | {periods['all']['models'][c]['logloss']:.6f} |")
    lines += ['', '## 整合性と制約', '', json.dumps(results['alignment'], ensure_ascii=False, indent=2), '',
              'S08のmetricsには競走全体loss/Brierとrich/sparseが保存されており、選択確率scalarだけでは分からない精度も再利用できた。',
              '価格/全horse ID/各過去時点の公表履歴の完全受入ではない。元政策の違いを含む保存研究の対応比較。',
              '2026東京秋は保存期間外。2026中山秋は9月のみ。2026がない場合を不振としない。',
              '区間は多重比較未補正。0的中bootstrapの[0,0]は将来ROI0の証明ではない。',
              '今回実用採用/モデルfit/SQL/API/本番変更0。全対象と比較指標の詳細はresults.json/ledger.json。']
    with (OUT/'report.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(lines)+'\n')


def main():
    """事前仕様を保存し、3panelの同一対象比較を実行して原本不変を照合する。"""
    OUT.mkdir(exist_ok=True)
    stage = 'protocol'
    try:
        spec = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/295-東京中山向け保存研究の固定再分析.md'
        save('protocol.json', {'spec_sha256': base.sha(spec), 'scopes': SCOPES, 'periods': PERIODS,
                              'V110_extra': ['both_all_long', 'both_autumn_long'],
                              'S08_extra': ['both_all_rich', 'both_all_sparse', 'both_autumn_rich', 'both_autumn_sparse'],
                              'bootstrap_seed': 295, 'bootstrap_draws': 2000, 'independent_test': False})
        stage = 'source'
        original, hashes = base.load()
        source = {}
        for r in original:
            if r['venue'] not in ('東京', '中山'):
                continue
            public = {'race_key': r['race_key'], 'race_date': r['race_date'], 'course': 'tokyo' if r['venue'] == '東京' else 'nakayama'}
            source[r['race_key']] = {'raw': r, 'models': {c: native(r[c]) for c in base.previous.CASES}, 'public': public, **public}
        stage = 'align_V110'
        vp, va = v110_panel(source, hashes)
        stage = 'align_S08'
        sp, sa = s08_panel(source, hashes)
        panels = {'base': [{**b['public'], 'models': b['models']} for b in source.values()], 'V110_common': vp, 'S08_common': sp}
        alignment = {'base_target_races': len(source), 'V110': va, 'S08': sa,
                     'saved_key_format': 'YYYYMMDD_course2_race2_native12', 'all_periods_already_seen': True}
        save('alignment.json', alignment)
        save('ledger.json', panels)
        stage = 'comparison'
        output = {}
        for name, rows in panels.items():
            scopes = list(SCOPES)
            if name == 'V110_common': scopes += ['both_all_long', 'both_autumn_long']
            if name == 'S08_common': scopes += ['both_all_rich', 'both_all_sparse', 'both_autumn_rich', 'both_autumn_sparse']
            output[name] = {scope: {period: compare(subset(rows, scope, period)) for period in PERIODS} for scope in scopes}
        assert all(base.sha(ROOT/p) == h for p, h in hashes.items())
        result = {'alignment': alignment, 'panels': output, 'source_sha256': hashes, 'source_unchanged': True,
                  'adoption': False, 'new_model_fits': 0, 'sql_queries': 0, 'api_requests': 0}
        save('results.json', result);render(result)
        print(json.dumps(alignment, ensure_ascii=False, indent=2))
        for name in panels:
            for scope in ('both_all', 'both_autumn'):
                print(name, scope, json.dumps({y: {c: {k:s[k] for k in ('bets', 'hits', 'roi', 'logloss')} for c,s in output[name][scope][y]['models'].items()} for y in ('2024', '2025', '2026')}, ensure_ascii=False))
    except Exception as error:
        save('failure.json', {'stage': stage, 'error_type': type(error).__name__, 'message': str(error)[:200]})
        raise


if __name__ == '__main__':
    main()
