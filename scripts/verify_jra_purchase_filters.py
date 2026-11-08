"""概要: 購入限定10条件の価格・全選択・精算・再抽出・採否を別式で検算する。
作成日: 2026-11-07
入力: 完了run、元dataset、保存予測と年別T30原本。
出力: run内の独立検算JSON。相違時は例外で終了。
実行例: uv run --frozen --extra ml python scripts/verify_jra_purchase_filters.py
注意事項: 学習・外部通信・採否変更なし。結果は新規作成のみ。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from datetime import datetime, timedelta
import gzip
import hashlib
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'artifacts/jra_research/market_attribute_chimera_20261024_v3'
S0 = ROOT / 'artifacts/jra_research/current_attributes_S0_20261025'


def read(path):
    """UTF-8 JSONを読み込む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """ストリームでSHA256を計算する。"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def independent_summary(rows):
    """購入済み行から独立に100円精算と配当依存を計算する。"""
    n = len(rows)
    wins = [r for r in rows if r['hit']]
    paid = sum(r['paid_yen'] for r in rows)
    largest = max([r['paid_yen'] for r in wins], default=0)
    equity = np.concatenate(([0], np.cumsum([r['paid_yen'] - 100 for r in rows], dtype=np.int64)))
    return {'purchases': n, 'purchase_days': len({r['race_date'] for r in rows}),
            'hits': len(wins), 'hit_rate': len(wins) / n if n else None,
            'stake_yen': n * 100, 'paid_yen': paid, 'net_yen': paid - n * 100,
            'roi_percent': paid / n if n else None,
            'mean_ev': sum(r['probability'] * r['odds'] for r in rows) / n if n else None,
            'max_drawdown_yen': int(np.max(np.maximum.accumulate(equity) - equity)),
            'largest_hit_yen': largest,
            'net_without_largest_hit_yen': paid - largest - (n - 1) * 100 if wins else -n * 100,
            'mean_hit_final_to_T30': sum(r['official_payout_yen'] / (100 * r['odds']) for r in wins) / len(wins) if wins else None}


def check_summary(rows, summary, opportunities):
    """独立指標を保存集計の全項目と照合する。"""
    expected = independent_summary(rows) | {'opportunities': opportunities,
                'purchase_rate': len(rows) / opportunities if opportunities else None}
    assert set(expected) == set(summary)
    for key, value in expected.items():
        actual = summary[key]
        assert actual is None if value is None else np.isclose(actual, value, atol=1e-9, rtol=1e-12), (key, actual, value)


def verify(folder):
    """原本から全選択行・条件を再構成し、統計と判定も独立に照合する。"""
    manifest = read(folder / 'manifest.json')
    for group in ('source_sha256', 'frozen_inputs_sha256'):
        assert all(sha(ROOT / p) == v for p, v in manifest[group].items()), group
    assert all(sha(folder / p) == v for p, v in manifest['files_sha256'].items())
    protocol = read(folder / 'protocol.json')
    expected_policies = [{'id': f'P{i + 1:02d}', 'min_ev': t, 'max_odds': cap}
                         for i, (cap, t) in enumerate((c, t) for c in (None, 20.) for t in (1., 1.05, 1.10, 1.15, 1.20))]
    assert protocol['policies'] == expected_policies
    data = joblib.load(REFERENCE / 'dataset.joblib')
    records = {r['race_id']: r for r in data['records'] + data['later'] if r['race_date'] >= '2023-01-01'}
    raw_prices = {}
    for relative, digest in read(folder / 'price-inputs.json')['sha256'].items():
        path = ROOT / relative
        assert sha(path) == digest
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                v = json.loads(line)
                if v['race_id'] not in records:
                    continue
                r = records[v['race_id']]
                q = v['inputs']['odds']['T-30m']['quinella']
                assert datetime.fromisoformat(q['cutoff']) + timedelta(minutes=30) == datetime.fromisoformat(v['race']['start_at'])
                assert datetime.fromisoformat(q['announced_at']) <= datetime.fromisoformat(q['cutoff'])
                mapping = {tuple(sorted([int(x['horse_no_1']), int(x['horse_no_2'])])): x['odds'] for x in q['pairs']}
                pp = list(combinations(map(int, r['horses']), 2))
                assert set(mapping) == set(pp)
                inv = np.array([1. / mapping[k] for k in pp])
                assert np.max(np.abs(inv / sum(inv) - r['market'])) < 1e-12
                result = v['result']['quinella_payout_per_100_yen']
                assert len(result) == 1
                pay = result[0]
                pair = tuple(sorted([int(pay['horse_no_1']), int(pay['horse_no_2'])]))
                assert pp[r['winner']] == pair
                ranks = {int(k): value for k, value in v['result']['ranks_by_horse'].items()}
                assert sorted(k for k, rank in ranks.items() if rank in (1, 2)) == list(pair)
                raw_prices[v['race_id']] = (mapping, int(pay['payout']), q)
    assert set(raw_prices) == set(records)
    rows = read(folder / 'selected-rows.json')
    row_maps = {label: {r['race_id']: r for r in rr} for label, rr in rows.items()}
    checked = 0
    for year in (2023, 2024, 2025, 2026):
        prefix = '2026_selected' if year == 2026 else f'{year}_D0'
        for label, directory, stem in (('D0', REFERENCE, prefix), ('S0', S0, f'{year}_S0')):
            cell = read(directory / (stem + '.json'))
            pp = joblib.load(directory / (stem + '_predictions.joblib'))
            assert len(cell['test_ids']) == len(pp)
            for key, p in zip(cell['test_ids'], pp, strict=True):
                r = records[key]
                row = row_maps[label][key]
                pair_list = list(combinations(r['horses'], 2))
                top = max(range(len(p)), key=lambda i: float(p[i]))
                pair = pair_list[top]
                mapping, payout, q = raw_prices[key]
                odds, probability = float(mapping[tuple(map(int, pair))]), float(p[top])
                hit = int(top == r['winner'])
                expected = {k: r[k] for k in ('race_id', 'race_date', 'course', 'surface', 'distance')}
                expected |= {'model': label, 'top_pair_index': top, 'pair': list(pair), 'probability': probability,
                    'odds': odds, 'ev': probability * odds, 'hit': hit, 'paid_yen': hit * payout,
                    'official_payout_yen': payout, 'announced_at': q['announced_at'], 'cutoff': q['cutoff'], 'raw_sha256': q['raw_sha256']}
                assert row == expected, (label, key)
                checked += 1
    assert all(len(rr) == len(records) for rr in rows.values())
    assessment = read(folder / 'assessment.json')
    days = sorted({r['race_date'] for r in rows['S0'] if r['race_date'] >= '2024-01-01'})
    assert days == assessment['opportunity_days']
    indices = np.random.default_rng(440).integers(0, len(days), size=(20000, len(days)), dtype=np.int32)
    labels, intervals_checked = [], 0
    for entry in assessment['entries']:
        label, policy = entry['model'], entry['policy']
        assert policy in expected_policies
        main = [r for r in rows[label] if r['race_date'] >= '2024-01-01']
        chosen = [r for r in main if r['probability'] * r['odds'] >= policy['min_ev']
                  and (policy['max_odds'] is None or r['odds'] <= 20)]
        assert entry['purchased_ids'] == [r['race_id'] for r in chosen]
        check_summary(chosen, entry['total'], len(main))
        for year in (2024, 2025, 2026):
            check_summary([r for r in chosen if r['race_date'].startswith(str(year))], entry['annual'][str(year)],
                          sum(r['race_date'].startswith(str(year)) for r in main))
        dev = [r for r in rows[label] if r['race_date'] < '2024-01-01']
        dev_chosen = [r for r in dev if r['probability'] * r['odds'] >= policy['min_ev']
                      and (policy['max_odds'] is None or r['odds'] <= 20)]
        check_summary(dev_chosen, entry['development_2023'], len(dev))
        daily = {d: [0, 0] for d in days}
        for r in chosen:
            daily[r['race_date']][0] += 100
            daily[r['race_date']][1] += r['paid_yen']
        values = np.array([daily[d] for d in days], dtype=np.int64)
        ratios = []
        for start in range(0, 20000, 200):
            totals = np.sum(values[indices[start:start + 200]], axis=1)
            ratios.extend(float(p / s * 100) if s else float('nan') for s, p in totals)
        finite = np.array([v for v in ratios if np.isfinite(v)])
        interval = entry['interval']
        assert interval['zero_stake_fraction'] == 1 - len(finite) / 20000 or np.isclose(interval['zero_stake_fraction'], 1 - len(finite) / 20000, atol=1e-15)
        if len(finite):
            assert np.allclose(interval['roi_ci95_percent'], np.percentile(finite, [2.5, 97.5]), atol=1e-9, rtol=1e-12)
            assert np.isclose(interval['roi_family_lower_percent'], np.percentile(finite, .25), atol=1e-9, rtol=1e-12)
        else:
            assert interval['roi_ci95_percent'] is None and interval['roi_family_lower_percent'] is None
        total, annual = entry['total'], entry['annual']
        checks = {'adequate': total['purchases'] >= 300 and total['hits'] >= 30 and total['purchase_days'] >= 50
                  and min(a['purchases'] for a in annual.values()) >= 100,
                  'pooled_positive': (total['roi_percent'] or 0) > 100,
                  'every_year_positive': all((a['roi_percent'] or 0) > 100 for a in annual.values()),
                  'family_lower_positive': (interval['roi_family_lower_percent'] or 0) > 100,
                  'without_largest_positive': total['net_without_largest_hit_yen'] > 0}
        expected = ('no_opportunities' if total['purchases'] == 0 else 'insufficient' if not checks['adequate'] else
                    'promising_historical_candidate' if all(checks.values()) else
                    ('positive_but_unconfirmed' if checks['every_year_positive'] else 'positive_but_unstable')
                    if checks['pooled_positive'] else 'unsupported')
        assert entry['decision'] == {'label': expected, 'checks': checks, 'purchase_allowed': False, 'unknown_test': False}
        labels.append((label, policy['id']))
        intervals_checked += 1
    assert labels == [(label, p['id']) for label in ('S0', 'D0') for p in expected_policies]
    for label in ('S0', 'D0'):
        main = [r for r in rows[label] if r['race_date'] >= '2024-01-01']
        check_summary(main, assessment['controls'][label]['total'], len(main))
        for year in (2024, 2025, 2026):
            rr = [r for r in main if r['race_date'].startswith(str(year))]
            check_summary(rr, assessment['controls'][label]['annual'][str(year)], len(rr))
    assert assessment['promising_cells'] == [e['model'] + '_' + e['policy']['id'] for e in assessment['entries']
                                            if e['decision']['label'] == 'promising_historical_candidate']
    result = {'status': 'passed', 'selected_rows': checked, 'market_vectors': len(records),
              'policy_cells': intervals_checked, 'bootstrap_samples': 20000, 'opportunity_days': len(days),
              'unknown_test': False, 'verifier_sha256': sha(Path(__file__))}
    with (folder / 'independent-verification.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/purchase_filters_20261107')
    verify(parser.parse_args().output)
