"""概要: 購入限定追加期間と全馬連選択の価格・候補・精算・統計・採否を検算する。
作成日: 2026-11-07
入力: 新規run、固定原本、保存年別確率。
出力: 独立検算JSON、不一致時は例外終了。
実行例: uv run --frozen --extra ml python scripts/verify_jra_purchase_followup.py
注意事項: 外部通信・学習・実購入なし。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import datetime
from itertools import combinations
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_purchase_followup as run
from verify_jra_purchase_filters import check_summary
from verify_jra_current_attributes import independent_predict


def independent_choices(p, o):
    """逐次列挙で候補を制限し、同点はペア順の先頭にする。"""
    top = max(range(len(p)), key=lambda i: p[i])
    result = {name: top if p[top] * o[top] >= threshold and (cap is None or o[top] <= cap) else None
              for name, threshold, cap in [('P01', 1., None), ('P02', 1.05, None), ('P06', 1., 20.)]}
    for name, minimum, maximum, threshold in [('A', .03, 20., 1.05), ('B', .03, 20., 1.10), ('C', .05, 15., 1.05)]:
        candidates = [i for i in range(len(p)) if p[i] >= minimum and 4 <= o[i] <= maximum and p[i] * o[i] >= threshold]
        result[name] = max(candidates, key=lambda i: p[i] * o[i]) if candidates else None
    return result


def validate_statistics(cells, saved, additional=False):
    """別集計で全精算・年別・20,000再抽出区間・固定採否を確認する。"""
    days = sorted({r['race_date'] for rows in cells.values() for r in rows})
    sample = np.random.default_rng(445).integers(0, len(days), (20000, len(days)), dtype=np.int32) if days else None
    for key, rows in cells.items():
        item = saved[key]
        chosen = [r for r in rows if r['buy']]
        check_summary(chosen, item['total'], len(rows))
        for year, annual in item['annual'].items():
            rr = [r for r in rows if r['race_date'].startswith(year)]
            check_summary([r for r in rr if r['buy']], annual, len(rr))
        daily = {d: [0, 0] for d in days}
        for r in chosen:
            daily[r['race_date']][0] += 100
            daily[r['race_date']][1] += r['paid_yen']
        values, ratios = np.asarray([daily[d] for d in days]), []
        if days:
            for i in range(0, 20000, 200):
                totals = values[sample[i:i + 200]].sum(axis=1)
                ratios.extend(paid / stake * 100 for stake, paid in totals if stake > 0)
        ci = item['interval']
        if ratios:
            assert np.allclose(ci['roi_ci95_percent'], np.percentile(ratios, [2.5, 97.5]), rtol=1e-12, atol=1e-9)
            assert np.isclose(ci['roi_family_lower_percent'], np.percentile(ratios, 5 / len(cells)), rtol=1e-12, atol=1e-9)
        else:
            assert ci['roi_ci95_percent'] is None and ci['roi_family_lower_percent'] is None
        assert np.isclose(ci['zero_stake_fraction'], 1 - len(ratios) / 20000)
        total = item['total']
        adequate = (total['purchases'] >= 100 and total['hits'] >= 20 and total['purchase_days'] >= 30) if additional else (
            total['purchases'] >= 300 and total['hits'] >= 30 and total['purchase_days'] >= 50
            and min(x['purchases'] for x in item['annual'].values()) >= 100)
        checks = {'adequate': adequate, 'pooled_positive': (total['roi_percent'] or 0) > 100,
                  'family_lower_positive': (ci['roi_family_lower_percent'] or 0) > 100,
                  'without_largest_positive': total['net_without_largest_hit_yen'] > 0}
        if not additional:
            checks['every_year_positive'] = all((x['roi_percent'] or 0) > 100 for x in item['annual'].values())
        label = ('no_opportunities' if not total['purchases'] else 'insufficient' if not adequate else
                 'promising_historical_candidate' if all(checks.values()) else 'unsupported' if additional or not checks['pooled_positive'] else
                 'positive_but_unconfirmed' if checks['every_year_positive'] else 'positive_but_unstable')
        assert item['decision']['checks'] == checks and item['decision']['label'] == label
        assert item['decision']['purchase_allowed'] is False


def check_rows(rows, probabilities, prices, choices, winners):
    """独立選択の全行を元の価格・確率と公式払戻へ照合する。"""
    count = 0
    for name, rr in rows.items():
        for r in rr:
            key = r['race_id']
            index = choices[key][name.split('_')[-1]]
            winner, payout = winners[key]
            p, o = probabilities[key], prices[key]
            buy, hit = index is not None, int(index is not None and index == winner)
            assert r['index'] == index and r['buy'] == buy and r['hit'] == hit
            assert r['official_payout_yen'] == payout and r['paid_yen'] == hit * payout
            assert r['probability'] == (float(p[index]) if buy else 0.)
            assert r['odds'] == (float(o[index]) if buy else 0.)
            assert r['ev'] == (float(p[index] * o[index]) if buy else 0.)
            count += 1
    return count


def verify(folder):
    """凍結SHAから全選択・全精算・区間・採否まで別手順で検算する。"""
    m = run.read(folder / 'manifest.json')
    for group in ('source_sha256', 'frozen_inputs_sha256'):
        assert all(run.sha(run.ROOT / p) == v for p, v in m[group].items())
    assert all(run.sha(folder / p) == v for p, v in m['files_sha256'].items())
    forecasts = run.read(folder / 'additional-forecasts.json')
    fitted = joblib.load(run.old.S0 / '2026_S0.joblib')
    pp, oo, cc = {}, {}, {}
    originals = {r['race_id']: r for r in run.readlines(run.VER / 'versioned-inputs.jsonl.gz')}
    receipt = {r['race_id']: r for r in run.readlines(run.CAP / 'inputs.jsonl.gz') if r['timing'] == 't_minus_30m'}
    for f in forecasts:
        key, obs = f['race_id'], f['observation']
        original = receipt[key] if f['source'] == 'receipt' else originals[key]
        assert original['odds'] == obs['odds'] and original['observed_at'] == obs['observed_at']
        assert (original['card'] if f['source'] == 'receipt' else original['card']['race'] | {'runners': original['card']['runners']}) == obs['card']
        assert max(datetime.fromisoformat(t) for t in obs['observed_at'].values()) < datetime.fromisoformat(obs['post_at'])
        if f['source'] == 'versioned':
            assert datetime.fromisoformat(original['card']['meta']['card_fetched_at']) <= min(datetime.fromisoformat(t) for t in obs['observed_at'].values())
        record = run.s0.from_capture(obs)
        p = independent_predict(fitted, record)
        assert np.allclose(p, f['probabilities'], rtol=1e-12, atol=1e-14)
        o = np.asarray(f['prices'])
        assert f['choices'] == independent_choices(p, o)
        pp[key], oo[key], cc[key] = np.asarray(f['probabilities']), o, independent_choices(np.asarray(f['probabilities']), o)
    canonical = run.read(run.CAP / 'canonical-results.json')
    ranks, payouts = {}, {}
    for r in canonical['result_entries']:
        ranks.setdefault(r['race_id'], []).append(r)
    for r in canonical['payouts']:
        if r['bet_type'] in ('quinella', '馬連'):
            payouts.setdefault(r['race_id'], []).append(r)
    winners = {}
    for r in run.read(folder / 'additional-settlements.json'):
        key = r['race_id']
        f = next(f for f in forecasts if f['race_id'] == key)
        top = sorted(int(x['horse_no']) for x in ranks[key] if x['rank'] is not None and int(x['rank']) in (1, 2))
        payout = payouts[key][0]
        assert top == sorted(map(int, re.findall(r'\d+', payout['combination']))) == list(map(int, r['pair']))
        winner = list(combinations(f['horses'], 2)).index(tuple(r['pair']))
        assert winner == r['winner'] and int(payout['payout']) == r['payout']
        winners[key] = (winner, r['payout'])
    additional = run.read(folder / 'additional-rows.json')
    checked = check_rows(additional, pp, oo, cc, winners)
    assert set(winners).isdisjoint(r['race_id'] for r in run.read(folder / 'additional-pending.json'))
    assert len(winners) + len(run.read(folder / 'additional-pending.json')) == len(forecasts)
    data = joblib.load(run.old.REFERENCE / 'dataset.joblib')
    records = {r['race_id']: r for r in data['records'] + data['later'] if r['race_date'] >= '2023-01-01'}
    odds, winners = {}, {}
    for relative in run.read(folder / 'price-inputs.json')['sha256']:
        for v in run.readlines(run.ROOT / relative):
            key = v['race_id']
            if key not in records:
                continue
            r = records[key]
            mapping = {tuple(sorted([int(x['horse_no_1']), int(x['horse_no_2'])])): x['odds'] for x in v['inputs']['odds']['T-30m']['quinella']['pairs']}
            odds[key] = np.array([mapping[k] for k in combinations(map(int, r['horses']), 2)])
            pay = v['result']['quinella_payout_per_100_yen'][0]
            assert list(combinations(map(int, r['horses']), 2))[r['winner']] == tuple(sorted([int(pay['horse_no_1']), int(pay['horse_no_2'])]))
            winners[key] = (r['winner'], int(pay['payout']))
    historical = run.read(folder / 'historical-rows.json')
    development = run.read(folder / 'development-rows.json')
    for label in ('S0', 'D0'):
        pp = {}
        for year in (2023, 2024, 2025, 2026):
            directory = run.old.S0 if label == 'S0' else run.old.REFERENCE
            stem = f'{year}_S0' if label == 'S0' else '2026_selected' if year == 2026 else f'{year}_D0'
            ids = run.read(directory / (stem + '.json'))['test_ids']
            values = joblib.load(directory / (stem + '_predictions.joblib'))
            pp.update(zip(ids, values, strict=True))
        choices = {key: independent_choices(p, odds[key]) for key, p in pp.items()}
        checked += check_rows({k: v for k, v in historical.items() if k.startswith(label)}, pp, odds, choices, winners)
        checked += check_rows({k: v for k, v in development.items() if k.startswith(label)}, pp, odds, choices, winners)
    a = run.read(folder / 'assessment.json')
    validate_statistics(additional, a['additional'], additional=True)
    validate_statistics(historical, a['historical'])
    for key, rows in development.items():
        check_summary([r for r in rows if r['buy']], a['development'][key], len(rows))
    result = {'status': 'passed', 'all_choice_settlement_rows': checked, 'additional_forecasts': len(forecasts),
              'additional_settled': len(additional['P01']), 'cells': 12, 'bootstrap': 20000,
              'unknown_test': False, 'verifier_sha256': run.sha(Path(__file__))}
    run.save(folder / 'independent-verification.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=run.ROOT / 'artifacts/jra_research/purchase_followup_20261107')
    verify(parser.parse_args().output)
