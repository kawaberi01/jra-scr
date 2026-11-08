"""概要: 条件制限の全購入判断・年境界・精算・日単位区間を別式で検算する。
作成日: 2026-11-07
入力: --runの固定原本・27セル・選別証跡。
出力: independent-verification.json、失敗時independent-failure.json。
実行例: uv run --frozen --extra ml python scripts/verify_jra_condition_gate.py
注意事項: 学習・外部通信・実購入なし。元の研究成果を上書きしない。
"""

import argparse
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np

import run_jra_condition_gate as run


def category(row, dimension):
    """本体と独立の境界式で条件名を構成する。"""
    distance = int(row['distance'])
    band = ('1400' if distance <= 1400 else '1800' if distance <= 1800 else
            '2200' if distance <= 2200 else '2600' if distance <= 2600 else '2601plus')
    c, s = str(int(row['course'])), str(int(row['surface']))
    return {'course': c, 'surface': s, 'distance': band,
            'course_surface': c + ':' + s, 'surface_distance': s + ':' + band}[dimension]


def eligible(rr, stable):
    """Python整数集計だけで、事前固定の過去実績条件を再判定する。"""
    bought = [r for r in rr if r['tickets'] > 0]
    years = {r['race_date'][:4] for r in bought}
    enough = len(bought) >= 30 and sum(r['hits'] for r in bought) >= 5 and len({r['race_date'] for r in bought}) >= 10
    positive = sum(r['paid_yen'] - 100 for r in bought) > 0
    annual = all(len([r for r in bought if r['race_date'].startswith(y)]) >= 10
                 and sum(r['paid_yen'] - 100 for r in bought if r['race_date'].startswith(y)) > 0 for y in years)
    return enough and positive and (annual or not stable)


def totals(rr):
    """精算行を独立に円単位集計し、単発配当除外と最大DDも検算する。"""
    purchased = [r for r in rr if r['tickets']]
    stake, paid = sum(r['stake_yen'] for r in rr), sum(r['paid_yen'] for r in rr)
    balance = peak = dd = 0
    for row in rr:
        balance += row['paid_yen'] - row['stake_yen']
        peak = max(peak, balance); dd = max(dd, peak - balance)
    return {'tickets': sum(r['tickets'] for r in rr), 'hits': sum(r['hits'] for r in rr),
            'purchase_days': len({r['race_date'] for r in purchased}), 'stake_yen': stake,
            'paid_yen': paid, 'net_yen': paid - stake, 'roi_percent': 100 * paid / stake if stake else None,
            'max_drawdown_yen': dd,
            'net_without_largest_hit_yen': paid - max((r['paid_yen'] for r in rr), default=0) - (stake - 100)
            if any(r['hits'] for r in rr) else -stake}


def verify(folder):
    """全選択・SHA・精算・区間を照合し、完了証跡を排他保存する。"""
    try:
        manifest = run.read(folder / 'manifest.json')
        for relative, digest in (manifest['source_sha256'] | manifest['frozen_inputs_sha256']).items():
            run.require(run.sha(run.ROOT / relative) == digest, 'gate_verify_source_sha')
        for name, digest in manifest['files_sha256'].items():
            run.require(run.sha(folder / name) == digest, 'gate_verify_output_sha')
        base, actual = run.read(folder / 'base-rows.json'), run.read(folder / 'settlement-rows.json')
        audit, assess = run.read(folder / 'selection-audit.json'), run.read(folder / 'assessment.json')
        expected, count = {}, 0
        for case, rr in base.items():
            control = [r for r in rr if r['race_date'] >= '2024-01-01']
            expected[case + '_control'] = control
            for dim in ('course', 'distance', 'surface', 'course_surface', 'surface_distance'):
                for stable in (False, True):
                    name = case + '_' + dim + ('_stable' if stable else '_pooled')
                    result = []
                    for year in (2024, 2025, 2026):
                        train = [r for r in rr if int(r['race_date'][:4]) < year]
                        test = [r for r in rr if int(r['race_date'][:4]) == year]
                        proof = audit[name][str(year)]
                        run.require(proof['train_ids'] == [r['race_id'] for r in train]
                                    and proof['test_ids'] == [r['race_id'] for r in test], 'gate_verify_temporal_boundary')
                        grouped = defaultdict(list)
                        for row in train:
                            grouped[category(row, dim)].append(row)
                        accepted = sorted(k for k, rows in grouped.items() if eligible(rows, stable))
                        run.require(proof['accepted_groups'] == accepted, 'gate_verify_accepted_group')
                        for row in test:
                            keep = category(row, dim) in accepted
                            result.append(row if keep else row | {'indices': [], 'tickets': 0, 'hits': 0, 'stake_yen': 0, 'paid_yen': 0})
                    expected[name] = result
        records = joblib.load(run.T10 / 'dataset.joblib')
        checked_m10 = []
        combination = {k: [] for k in run.CONSENSUS}
        for year in (2023, 2024, 2025, 2026):
            test = [r for r in records if int(r['race_date'][:4]) == year]
            mm, ss, tt = [joblib.load(run.T10 / f'{year}_{case}_predictions.joblib') for case in ('M10', 'S0_direct', 'S10')]
            for r, m, s, t in zip(test, mm, ss, tt, strict=True):
                choices = [i for i in range(len(m)) if float(m[i]) >= .03 and 4 <= float(r['prices'][i]) <= 20
                           and float(m[i]) * float(r['prices'][i]) >= 1.05]
                choices.sort(key=lambda i: (-float(m[i] * r['prices'][i]), i))
                chosen = choices[:1]
                hit = int(r['winner'] in chosen)
                row = {k: r[k] for k in ('race_id', 'race_date')} | {k: int(r[k]) for k in ('course', 'surface', 'distance')} | {
                    'indices': chosen, 'tickets': len(chosen), 'hits': hit, 'stake_yen': 100 * len(chosen),
                    'paid_yen': int(r['payout_yen']) * hit, 'official_payout_yen': int(r['payout_yen'])}
                checked_m10.append(row)
                for name in run.CONSENSUS:
                    accept = False
                    if chosen:
                        i = chosen[0]
                        e0 = float(s[i] * r['prices'][i]) >= 1
                        e1 = float(t[i] * r['prices'][i]) >= 1
                        accept = {'top1': i == int(np.argmax(s)), 'top3': sum(v > s[i] for v in s) < 3,
                                  'S0_ev': e0, 'S10_ev': e1, 'both_ev': e0 and e1}[name]
                    combination[name].append(row if accept else row | {'indices': [], 'tickets': 0, 'hits': 0, 'stake_yen': 0, 'paid_yen': 0})
        run.require(checked_m10 == base['M10_A'], 'gate_verify_M10_base')
        source = run.read(run.S0 / 'selected-rows.json')['S0']
        for row, raw in zip(base['S0_P01'], source, strict=True):
            buy = raw['probability'] * raw['odds'] >= 1
            run.require(row['race_id'] == raw['race_id'] and row['tickets'] == int(buy)
                        and row['paid_yen'] == (raw['official_payout_yen'] * raw['hit'] if buy else 0), 'gate_verify_S0_base')
        for name, rr in combination.items():
            expected['M10_consensus_' + name] = [r for r in rr if r['race_date'] >= '2024-01-01']
        run.require(expected == actual, 'gate_verify_all_selection_settlement')
        days = sorted({r['race_date'] for rr in actual.values() for r in rr})
        samples = np.random.default_rng(450).integers(0, len(days), (20000, len(days)), dtype=np.int32)
        di = {d: i for i, d in enumerate(days)}
        for name, rr in actual.items():
            for period in ('total', '2024', '2025', '2026'):
                subset = rr if period == 'total' else [r for r in rr if r['race_date'].startswith(period)]
                saved = assess[name]['total'] if period == 'total' else assess[name]['annual'][period]
                for key, value in totals(subset).items():
                    run.require(saved[key] == value or (key == 'roi_percent' and value is not None and abs(saved[key] - value) < 1e-10), 'gate_verify_cash_total')
            daily_s, daily_p = np.zeros(len(days)), np.zeros(len(days))
            for r in rr:
                daily_s[di[r['race_date']]] += r['stake_yen']
                daily_p[di[r['race_date']]] += r['paid_yen']
            values = []
            for first in range(0, len(samples), 200):
                ss = daily_s[samples[first:first+200]].sum(axis=1)
                pp = daily_p[samples[first:first+200]].sum(axis=1)
                values.extend((100 * pp[ss > 0] / ss[ss > 0]).tolist())
            interval = assess[name]['interval']
            if values:
                run.require(np.allclose(interval['roi_ci95_percent'], np.quantile(values, [.025, .975]), atol=1e-10, rtol=0)
                            and abs(interval['roi_family_lower_percent'] - float(np.quantile(values, .05 / 27))) < 1e-10, 'gate_verify_interval')
            else:
                run.require(interval['roi_ci95_percent'] is None and interval['roi_family_lower_percent'] is None, 'gate_verify_empty_interval')
            run.require(abs(interval['zero_stake_fraction'] - (1 - len(values)/20000)) < 1e-12, 'gate_verify_zero_stake')
            count += len(rr)
        run.save(folder / 'independent-verification.json', {'status': 'passed', 'cells': len(actual),
            'selection_settlement_rows': count, 'temporal_folds': len(audit) * 3,
            'stats_cells': len(actual) * 4, 'bootstrap': 20000, 'new_fits': 0})
        print('independent_passed', len(actual), count, flush=True)
    except Exception as error:
        run.save(folder / 'independent-failure.json', {'type': type(error).__name__, 'reason': getattr(error, 'reason', str(error))})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=run.ROOT / 'artifacts/jra_research/condition_gate_20261107')
    verify(parser.parse_args().run)
