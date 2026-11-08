"""概要: 時点別固定選択と複数点精算・統計を別式で検算する。
作成日: 2026-11-07
入力: 完了run、元dataset・年別保存確率・オッズ原本。
出力: 独立検算JSON。不一致は例外で停止。
実行例: uv run --frozen --extra ml python scripts/verify_jra_purchase_operability.py
注意事項: 外部通信・結果書込・学習なし。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import datetime
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np
import run_jra_purchase_operability as run
from verify_jra_current_attributes import independent_predict


def choose(p, o):
    """逐次候補列挙でEV順と確率1位の選択を独立に求める。"""
    top = max(range(len(p)), key=lambda i: p[i])
    eligible = [i for i in range(len(p)) if p[i] >= .03 and 4 <= o[i] <= 20 and p[i] * o[i] >= 1.05]
    ordered = sorted(eligible, key=lambda i: (-p[i] * o[i], i))
    return {'P01': [top] if p[top] * o[top] >= 1 else [], 'A': ordered[:1], 'A2': ordered[:2], 'A3': ordered[:3]}


def statistics(cells, saved, historical):
    """実点数と同日依存を使い、全集計/区間/採否を独立再計算する。"""
    days = sorted({r['race_date'] for rows in cells.values() for r in rows})
    samples = np.random.default_rng(450).integers(0, len(days), (20000, len(days)), dtype=np.int32) if days else None
    for name, rows in cells.items():
        item = saved[name]
        for year, s in [('total', item['total'])] + list(item['annual'].items()):
            rr = rows if year == 'total' else [r for r in rows if r['race_date'].startswith(year)]
            n = sum(len(r['indices']) for r in rr)
            bought = [r for r in rr if r['indices']]
            hits = sum(r['hits'] for r in rr)
            paid = sum(r['paid_yen'] for r in rr)
            assert s['opportunities'] == len(rr) and s['tickets'] == n and s['purchased_races'] == len(bought)
            assert s['stake_yen'] == 100 * n and s['paid_yen'] == paid and s['net_yen'] == paid - n * 100
            assert s['hits'] == hits and s['purchase_days'] == len({r['race_date'] for r in bought})
            assert s['roi_percent'] is None if not n else np.isclose(s['roi_percent'], paid / n)
            assert s['ticket_hit_rate'] is None if not n else np.isclose(s['ticket_hit_rate'], hits / n)
            assert s['race_hit_rate'] is None if not bought else np.isclose(s['race_hit_rate'], hits / len(bought))
            assert s['purchase_rate'] is None if not rr else np.isclose(s['purchase_rate'], len(bought) / len(rr))
            balance, peak, dd = 0, 0, 0
            for r in rr:
                balance += r['paid_yen'] - r['stake_yen']
                peak = max(peak, balance)
                dd = max(dd, peak - balance)
            assert dd == s['max_drawdown_yen']
            largest = max([r['paid_yen'] for r in rr], default=0)
            assert s['net_without_largest_hit_yen'] == (paid - largest - n * 100 + 100 if hits else -n * 100)
        daily = {d: [0, 0] for d in days}
        for r in rows:
            daily[r['race_date']][0] += r['stake_yen']
            daily[r['race_date']][1] += r['paid_yen']
        array, ratios = np.asarray([daily[d] for d in days]), []
        if days:
            for start in range(0, 20000, 200):
                sums = array[samples[start:start + 200]].sum(axis=1)
                ratios.extend(p / s * 100 for s, p in sums if s > 0)
        interval = item['interval']
        assert np.isclose(interval['zero_stake_fraction'], 1 - len(ratios) / 20000)
        if ratios:
            assert np.allclose(interval['roi_ci95_percent'], np.percentile(ratios, [2.5, 97.5]), rtol=1e-12, atol=1e-9)
            assert np.isclose(interval['roi_family_lower_percent'], np.percentile(ratios, 5 / len(cells)), rtol=1e-12, atol=1e-9)
        else:
            assert interval['roi_ci95_percent'] is None and interval['roi_family_lower_percent'] is None
        t = item['total']
        checks = {'adequate': t['tickets'] >= (300 if historical else 100) and t['hits'] >= (30 if historical else 20)
                  and t['purchase_days'] >= (50 if historical else 30)
                  and (not historical or all(v['tickets'] >= 100 for v in item['annual'].values())),
                  'pooled_positive': (t['roi_percent'] or 0) > 100,
                  'every_year_positive': all((v['roi_percent'] or 0) > 100 for v in item['annual'].values()),
                  'family_lower_positive': (interval['roi_family_lower_percent'] or 0) > 100,
                  'without_largest_positive': t['net_without_largest_hit_yen'] > 0}
        label = ('no_opportunities' if not t['tickets'] else 'insufficient' if not checks['adequate'] else
                 'promising_historical_candidate' if all(checks.values()) else 'positive_but_unconfirmed'
                 if checks['pooled_positive'] else 'unsupported')
        assert item['decision']['checks'] == checks and item['decision']['label'] == label


def verify(folder):
    """原本由来の価格・全時点確率・候補・公式精算を照合する。"""
    manifest = run.read(folder / 'manifest.json')
    for group in ('source_sha256', 'frozen_inputs_sha256'):
        assert all(run.sha(run.ROOT / p) == h for p, h in manifest[group].items())
    assert all(run.sha(folder / p) == h for p, h in manifest['files_sha256'].items())
    forecasts = run.read(folder / 'frozen-forecasts.json')
    fitted = joblib.load(run.prior.old.S0 / '2026_S0.joblib')
    keyed = {}
    for f in forecasts:
        r = run.prior.s0.from_capture(f['observation'])
        p = independent_predict(fitted, r)
        assert np.allclose(p, f['probabilities'], rtol=1e-12, atol=1e-14)
        mapping = {tuple(v['combination']): v['odds'] for v in f['observation']['odds']['quinella']}
        assert [mapping[k] for k in combinations(f['horses'], 2)] == f['prices']
        assert choose(np.asarray(f['probabilities']), np.asarray(f['prices'])) == f['choices']
        post = datetime.fromisoformat(f['post_at'])
        bounds = {'t_minus_30m': (25, 35), 't_minus_10m': (7, 13), 't_minus_2m': (.5, 4)}
        lo, hi = bounds[f['timing']]
        assert all(lo <= (post - datetime.fromisoformat(t)).total_seconds() / 60 <= hi for t in f['observation']['observed_at'].values())
        keyed[(f['race_id'], f['timing'])] = f
    accepted, rejected = run.outcomes(run.read(folder / 'canonical-results.json'))
    assert accepted == run.read(folder / 'official-outcomes.json') and rejected == run.read(folder / 'excluded-results.json')
    extra = run.read(folder / 'additional-rows.json')
    checked = 0
    for name, rows in extra.items():
        timing, rule = name.rsplit('_', 1)
        for r in rows:
            f = keyed[(r['race_id'], timing)]
            outcome = accepted[r['race_id']]
            pairs = list(combinations(f['horses'], 2))
            winner = pairs.index(tuple(outcome['pair'])) if tuple(outcome['pair']) in pairs else -1
            assert r['indices'] == f['choices'][rule]
            assert r['tickets'] == len(r['indices']) and r['stake_yen'] == 100 * len(r['indices'])
            assert r['hits'] == int(winner in r['indices']) and r['paid_yen'] == outcome['payout'] * r['hits']
            checked += 1
    data = joblib.load(run.prior.old.REFERENCE / 'dataset.joblib')
    records = {r['race_id']: r for r in data['records'] + data['later'] if r['race_date'] >= '2023-01-01'}
    prices = {}
    for relative in run.read(folder / 'price-inputs.json')['sha256']:
        for v in run.prior.readlines(run.ROOT / relative):
            if v['race_id'] not in records:
                continue
            r = records[v['race_id']]
            mapping = {tuple(sorted([int(x['horse_no_1']), int(x['horse_no_2'])])): x['odds'] for x in v['inputs']['odds']['T-30m']['quinella']['pairs']}
            prices[v['race_id']] = np.array([mapping[k] for k in combinations(map(int, r['horses']), 2)])
    hist, dev = run.read(folder / 'historical-rows.json'), run.read(folder / 'development-rows.json')
    official = run.prior.read(run.prior.old.OUTCOMES)
    for label in ('S0', 'D0'):
        pp = {}
        for year in (2023, 2024, 2025, 2026):
            directory = run.prior.old.S0 if label == 'S0' else run.prior.old.REFERENCE
            stem = f'{year}_S0' if label == 'S0' else '2026_selected' if year == 2026 else f'{year}_D0'
            pp.update(zip(run.read(directory / (stem + '.json'))['test_ids'], joblib.load(directory / (stem + '_predictions.joblib')), strict=True))
        for group in (hist, dev):
            for name, rows in group.items():
                if not name.startswith(label):
                    continue
                rule = name.split('_')[1]
                for r in rows:
                    key = r['race_id']; source = records[key]
                    selected = choose(pp[key], prices[key])[rule]
                    payout = source['payout_yen'] if key[:4] == '2023' else official[key]['payout_per_100_yen']
                    assert r['indices'] == selected and r['tickets'] == len(selected) and r['stake_yen'] == len(selected) * 100
                    assert r['hits'] == int(source['winner'] in selected) and r['paid_yen'] == r['hits'] * payout
                    checked += 1
    a = run.read(folder / 'assessment.json')
    statistics(extra, a['additional'], False)
    statistics(hist, a['historical'], True)
    result = {'status': 'passed', 'forecast_distributions': len(forecasts), 'choice_settlement_rows': checked,
              'statistical_cells': 18, 'bootstrap': 20000, 'unknown_test': False, 'verifier_sha256': run.sha(Path(__file__))}
    run.save(folder / 'independent-verification.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=run.ROOT / 'artifacts/jra_research/purchase_operability_20261107')
    verify(parser.parse_args().output)
