"""概要: 購入限定の追加期間3条件と全馬連期待値選択3条件を固定比較する。
作成日: 2026-11-07
入力: spec445、SHA固定旧研究、最新SQL凍結原本/版管理入力と保存結果。
出力: 新規runの予測/事前選択、結果待ち、期間別精算・採否・SHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_purchase_followup.py
注意事項: 0fit、SQL/HTTP書込なし。追加期間も保存入力からの事後再計算。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from collections import Counter
from datetime import datetime
import gzip
from itertools import combinations
import json
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_purchase_filters as old
from jra_srb import jra_research_purchase_ev as ev
from jra_srb import jra_research_current_attributes as s0

ROOT, read, save, sha, require = old.ROOT, old.read, old.save, old.sha, old.require
CAP = ROOT / 'artifacts/jra_research/purchase_capture_20261107'
VER = ROOT / 'artifacts/jra_research/purchase_versioned_20261107'
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/445-購入限定の未使用期間と全馬連期待値選択.md'


def readlines(path):
    """凍結済みJSONL.gzを読み、外部への問い合わせは行わない。"""
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def sources():
    """今回の仕様と実装、再利用するコードのSHAを凍結する。"""
    return {str(p.relative_to(ROOT)): sha(p) for p in (
        SPEC, Path(__file__), Path(ev.__file__), Path(s0.__file__), Path(old.__file__),
        ROOT / 'src/jra_srb/jra_research_purchase_filters.py', ROOT / 'scripts/audit_jra_versioned_links.py',
        ROOT / 'scripts/audit_jra_forward_capture.py', ROOT / 'scripts/verify_jra_purchase_followup.py',
        ROOT / 'tests/test_jra_purchase_ev.py')}


def choose(p, prices):
    """結果を受け取らず、上位確率限定3案と全馬連E選択3案を決める。"""
    top = int(np.argmax(p))
    result = {}
    for policy in old.model.policies():
        if policy['id'] in ('P01', 'P02', 'P06'):
            result[policy['id']] = top if old.model.accepts(float(p[top]), float(prices[top]), policy) else None
    return result | {c['id']: ev.select(p, prices, c) for c in ev.policies()}


def row(record, p, prices, index, payout, winner):
    """保存済み選択を公式結果へ結合し、買わない行は支出0用に残す。"""
    buy = index is not None
    hit = int(buy and index == winner)
    return {k: record[k] for k in ('race_id', 'race_date')} | {
        'buy': buy, 'index': index, 'probability': float(p[index]) if buy else 0.,
        'odds': float(prices[index]) if buy else 0., 'ev': float(p[index] * prices[index]) if buy else 0.,
        'hit': hit, 'paid_yen': payout * hit, 'official_payout_yen': payout}


def prepare_forward(folder):
    """時点適格な入力を結果を読まず選び、S0確率と全6選択を先に保存する。"""
    originals = readlines(CAP / 'inputs.jsonl.gz')
    versioned = readlines(VER / 'versioned-inputs.jsonl.gz')
    candidates, excluded = {}, []
    fitted = joblib.load(old.S0 / '2026_S0.joblib')
    for source, observations in (('receipt', originals), ('versioned', versioned)):
        for source_row in observations:
            r = dict(source_row)
            try:
                if r['timing'] != 't_minus_30m':
                    continue
                require(len(r['race_id']) == 12 and r['race_date'] > '2026-09-22', 'outside_additional_JRA')
                if source == 'versioned':
                    r['card'] = r['card']['race'] | {'runners': r['card']['runners']}
                post = datetime.fromisoformat(r['post_at'])
                observed = [datetime.fromisoformat(v) for v in r['observed_at'].values()]
                remaining = [(post - t).total_seconds() / 60 for t in observed]
                require(all(25 <= t <= 35 for t in remaining)
                        and (max(observed) - min(observed)).total_seconds() <= 300, 'timing_outside_fixed_range')
                if source == 'receipt':
                    require(datetime.fromisoformat(r['decision_at']) < post, 'late_receipt')
                if r['race_id'] in candidates:
                    continue
                record = s0.from_capture(r)
                p = s0.predict(fitted, record)
                pairs = list(combinations(record['horses'], 2))
                mapping = {tuple(x['combination']): x['odds'] for x in r['odds']['quinella']}
                prices = np.asarray([mapping[k] for k in pairs], dtype=float)
                candidates[r['race_id']] = {'race_id': record['race_id'], 'race_date': record['race_date'],
                    'source': source, 'observation': r, 'horses': record['horses'], 'probabilities': p.tolist(),
                    'prices': prices.tolist(), 'choices': choose(p, prices), 'prediction_saved_before_post': False}
            except Exception as error:
                excluded.append({'race_id': r['race_id'], 'source': source, 'reason': getattr(error, 'reason', str(error))})
    values = sorted(candidates.values(), key=lambda r: r['race_id'])
    save(folder / 'additional-forecasts.json', values)
    save(folder / 'additional-excluded.json', excluded)
    return values


def settle_forward(forecasts, folder):
    """確率と選択の保存後に結果/順位/公式馬連払戻を照合する。"""
    canonical = read(CAP / 'canonical-results.json')
    result_ids = {r['race_id'] for r in canonical['race_results']}
    payouts, ranks = {}, {}
    for p in canonical['payouts']:
        if p['bet_type'] in ('quinella', '馬連'):
            payouts.setdefault(p['race_id'], []).append(p)
    for r in canonical['result_entries']:
        ranks.setdefault(r['race_id'], []).append(r)
    cells = {name: [] for name in ('P01', 'P02', 'P06', 'A', 'B', 'C')}
    pending, settled = [], []
    for f in forecasts:
        key = f['race_id']
        if key not in result_ids or key not in payouts or key not in ranks:
            pending.append({'race_id': key, 'reason': 'complete_official_result_not_saved', 'choices': f['choices']})
            continue
        pp = payouts[key]
        require(len(pp) == 1, 'ambiguous_forward_settlement')
        pair = tuple(f'{int(x):02d}' for x in sorted(map(int, re.findall(r'\d+', pp[0]['combination']))))
        top = tuple(sorted(f"{int(r['horse_no']):02d}" for r in ranks[key]
                           if r['rank'] is not None and int(r['rank']) in (1, 2)))
        require(pair == top and len(pair) == 2, 'forward_rank_payout_mismatch')
        pairs = list(combinations(f['horses'], 2))
        require(pair in pairs and int(pp[0]['payout']) > 0, 'forward_settlement_roster')
        winner, pay = pairs.index(pair), int(pp[0]['payout'])
        settled.append({'race_id': key, 'winner': winner, 'pair': list(pair), 'payout': pay})
        p, prices = np.asarray(f['probabilities']), np.asarray(f['prices'])
        for name, index in f['choices'].items():
            cells[name].append(row(f, p, prices, index, pay, winner))
    save(folder / 'additional-settlements.json', settled)
    save(folder / 'additional-pending.json', pending)
    save(folder / 'additional-rows.json', cells)
    return cells, pending


def historical(folder):
    """保存年別確率を変えず、全馬連からの固定3条件を両モデルに適用する。"""
    records, later, d0 = old.reuse.load_inputs(folder)
    records = [r for r in records + later if r['race_date'] >= '2023-01-01']
    prices = old.prices_for(records, folder)
    cells = {label + '_' + c['id']: [] for label in ('S0', 'D0') for c in ev.policies()}
    dev = {key: [] for key in cells}
    for year in (2023, 2024, 2025, 2026):
        test = [r for r in records if r['race_date'].startswith(str(year))]
        require(read(old.S0 / f'{year}_S0.json')['test_ids'] == [r['race_id'] for r in test], 'followup_ids')
        ps = joblib.load(old.S0 / f'{year}_S0_predictions.joblib')
        for r, p0 in zip(test, ps, strict=True):
            price = prices[r['race_id']]
            for label, p in (('S0', p0), ('D0', d0[r['race_id']])):
                for c in ev.policies():
                    index = ev.select(p, price['odds'], c)
                    (dev if year == 2023 else cells)[label + '_' + c['id']].append(
                        row(r, p, price['odds'], index, price['payout'], r['winner']))
    save(folder / 'historical-rows.json', cells)
    save(folder / 'development-rows.json', dev)
    return cells, dev


def run(folder):
    """両研究を固定3条件ずつ完了し、失敗は証跡を残して採否を止める。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'freeze'
    try:
        initial = sources()
        frozen = {}
        for directory in (CAP, VER):
            manifest = read(directory / 'manifest.json')
            require(manifest['status'] == 'complete', 'capture_incomplete')
            for filename, digest in manifest['files_sha256'].items():
                require(sha(directory / filename) == digest, 'capture_changed')
                frozen[str((directory / filename).relative_to(ROOT))] = digest
        prior = read(ROOT / 'artifacts/jra_research/purchase_filters_20261107/manifest.json')
        frozen.update(prior['frozen_inputs_sha256'])
        frozen[str((old.S0 / '2026_S0.joblib').relative_to(ROOT))] = read(old.S0 / 'manifest.json')['model_sha256']['2026_S0.joblib']
        require(all(sha(ROOT / p) == v for p, v in frozen.items()), 'followup_input_sha')
        save(folder / 'protocol.json', {'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'ev_policies': ev.policies(), 'top1_policies': ['P01', 'P02', 'P06'], 'seed': 445,
            'new_fits': 0, 'unknown_test': False, 'purchase_allowed': False})
        stage = 'additional_predictions_before_outcomes'
        forecasts = prepare_forward(folder)
        stage = 'additional_settlement'
        additional, pending = settle_forward(forecasts, folder)
        stage = 'historical_ev'
        cells, dev = historical(folder)
        assessment = {'additional': ev.assess(additional, forward=True), 'historical': ev.assess(cells),
            'development': {key: old.model.summarize(rr, [r['buy'] for r in rr]) for key, rr in dev.items()},
            'additional_coverage': {'forecasts': len(forecasts), 'settled': len(forecasts) - len(pending),
                'pending': len(pending), 'by_date': dict(Counter(f['race_date'] for f in forecasts)),
                'source_counts': dict(Counter(f['source'] for f in forecasts)), 'original_prediction_performance': False},
            'new_fits': 0, 'purchase_allowed': False, 'unknown_test': False}
        save(folder / 'assessment.json', assessment)
        require(sources() == initial and all(sha(ROOT / p) == v for p, v in frozen.items()), 'followup_source_changed')
        save(folder / 'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        print(json.dumps({'status': 'complete', 'coverage': assessment['additional_coverage'],
            'historical': {k: (v['total']['purchases'], v['total']['roi_percent'], v['decision']['label']) for k, v in assessment['historical'].items()},
            'additional': {k: (v['total']['purchases'], v['total']['roi_percent'], v['decision']['label']) for k, v in assessment['additional'].items()}}), flush=True)
    except Exception as error:
        save(folder / 'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', str(error))})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/purchase_followup_20261107')
    run(parser.parse_args().output)
