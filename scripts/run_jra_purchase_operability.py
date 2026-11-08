"""概要: 固定選択後の公式結果を回収し、時点/点数分散を比較する。
作成日: 2026-11-07
入力: spec450、旧予測、保存原本、保存年別確率、ローカルAPI。
出力: 新規runの事前固定選択、結果回収台帳、SQL断面、全精算/比較/SHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_purchase_operability.py
注意事項: 対象公式結果のみSQL保存。3連続エラーで回収停止。学習/実購入/設定変更なし。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import datetime, timedelta, timezone
from itertools import combinations
import json
from pathlib import Path
import re
import time

import httpx
import joblib
import numpy as np

import run_jra_purchase_followup as prior
from jra_srb import jra_research_purchase_portfolio as policy
from jra_srb.storage import build_analysis_store

ROOT, read, save, sha, require = prior.ROOT, prior.read, prior.save, prior.sha, prior.require
PREVIOUS = ROOT / 'artifacts/jra_research/purchase_followup_20261107_v2'
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/450-継続研究の結果回収と時点分散比較.md'
COURSES = {1: 'sapporo', 2: 'hakodate', 3: 'fukushima', 4: 'niigata', 5: 'tokyo', 6: 'nakayama', 7: 'chukyo', 8: 'kyoto', 9: 'hanshin', 10: 'kokura'}


def sources():
    """実行開始前に仕様/コード/再利用部品のSHAを固定する。"""
    return {str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(policy.__file__),
        Path(prior.__file__), Path(prior.s0.__file__), ROOT / 'scripts/verify_jra_purchase_operability.py',
        ROOT / 'tests/test_jra_purchase_portfolio.py')}


def forecasts(folder):
    """全時点の確率/価格/固定選択を、結果取得より先に排他保存する。"""
    values, excluded = [], []
    for f in read(PREVIOUS / 'additional-forecasts.json'):
        values.append({k: f[k] for k in ('race_id', 'race_date', 'horses', 'probabilities', 'prices', 'source')} |
                      {'timing': 't_minus_30m', 'post_at': f['observation']['post_at'],
                       'observation': f['observation'], 'choices': policy.select(f['probabilities'], f['prices'])})
    fitted = joblib.load(prior.old.S0 / '2026_S0.joblib')
    bounds = {'t_minus_10m': (7, 13, 180), 't_minus_2m': (.5, 4, 90)}
    for obs in prior.readlines(prior.CAP / 'inputs.jsonl.gz'):
        if obs['timing'] not in bounds:
            continue
        try:
            lo, hi, gap = bounds[obs['timing']]
            post = datetime.fromisoformat(obs['post_at'])
            times = [datetime.fromisoformat(t) for t in obs['observed_at'].values()]
            require(all(lo <= (post - t).total_seconds() / 60 <= hi for t in times)
                    and (max(times) - min(times)).total_seconds() <= gap
                    and datetime.fromisoformat(obs['decision_at']) < post, 'operability_timing')
            r = prior.s0.from_capture(obs)
            p = prior.s0.predict(fitted, r)
            mapping = {tuple(e['combination']): e['odds'] for e in obs['odds']['quinella']}
            o = np.asarray([mapping[k] for k in combinations(r['horses'], 2)])
            values.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'timing': obs['timing'],
                'post_at': obs['post_at'], 'horses': r['horses'], 'probabilities': p.tolist(), 'prices': o.tolist(),
                'observation': obs, 'source': 'receipt', 'choices': policy.select(p, o)})
        except Exception as error:
            excluded.append({'race_id': obs['race_id'], 'timing': obs['timing'], 'reason': getattr(error, 'reason', str(error))})
    require(len({(f['race_id'], f['timing']) for f in values}) == len(values), 'duplicate_time')
    save(folder / 'frozen-forecasts.json', values)
    save(folder / 'excluded-times.json', excluded)
    return values


def collect(folder, values):
    """終了15分後の固定対象だけ公式結果を保存し、三連続エラーで止める。"""
    store = build_analysis_store()
    with store._connect(read_only=True) as c:
        existing = {r[0] for r in c._raw('SELECT race_id FROM api_runtime.race_results WHERE race_id>=? AND race_id<?',
                    ('202609230000', '202611080000')).fetchall()}
    frozen_at = datetime.now(timezone.utc)
    by_id = {f['race_id']: f for f in values}
    attempts, failures = [], 0
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=40.) as client, (folder / 'fetch-attempts.jsonl').open('x', encoding='utf-8') as stream:
        for key, f in sorted(by_id.items()):
            if key in existing:
                continue
            row = {'race_id': key}
            if datetime.fromisoformat(f['post_at']) + timedelta(minutes=15) > frozen_at:
                row['status'] = 'not_due'
            else:
                course = COURSES[int(key[8:10])]
                day = datetime.strptime(key[:8], '%Y%m%d').date().isoformat()
                try:
                    response = client.post(f'/jra/meetings/{day}/{course}/races/{int(key[10:])}/result/save')
                    response.raise_for_status()
                    payload = response.json()
                    require(payload['race_id'] == key and payload['results'] > 0 and payload['payouts'] > 0, 'result_identity')
                    row |= {'status': 'saved', 'response': payload}
                    failures = 0
                except Exception as error:
                    row |= {'status': 'error', 'reason': type(error).__name__}
                    if isinstance(error, httpx.HTTPStatusError):
                        row['http_status'] = error.response.status_code
                        row['body_excerpt'] = error.response.text[:300]
                    failures += 1
                time.sleep(.2)
            attempts.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            print('result_fetch', key, row['status'], flush=True)
            if failures >= 3:
                break
    save(folder / 'result-fetch-summary.json', {'frozen_at': frozen_at.isoformat(), 'forecast_sha256': sha(folder / 'frozen-forecasts.json'),
        'saved': sum(r['status'] == 'saved' for r in attempts), 'errors': sum(r['status'] == 'error' for r in attempts),
        'not_due': sum(r['status'] == 'not_due' for r in attempts), 'stopped_after_three_errors': failures >= 3})
    canonical = {}
    with store._connect(read_only=True) as c:
        for table in ('race_results', 'result_entries', 'payouts'):
            rows = c._raw(f'SELECT TOP(10001) * FROM api_runtime.{table} WHERE race_id>=? AND race_id<?',
                          ('202609230000', '202611080000')).fetchall()
            require(len(rows) <= 10000, 'result_read_bound')
            canonical[table] = [dict(r) for r in rows]
    save(folder / 'canonical-results.json', canonical)
    return canonical


def outcomes(canonical):
    """結果名簿・公式1/2着・馬連払戻を照合した精算辞書を作る。"""
    ids = {r['race_id'] for r in canonical['race_results']}
    ranks, pays = {}, {}
    for r in canonical['result_entries']:
        if r['rank'] is not None and int(r['rank']) in (1, 2):
            ranks.setdefault(r['race_id'], []).append(int(r['horse_no']))
    for r in canonical['payouts']:
        if r['bet_type'] in ('quinella', '馬連'):
            pays.setdefault(r['race_id'], []).append(r)
    accepted, rejected = {}, []
    for key in ids & set(ranks) & set(pays):
        if len(ranks[key]) != 2 or len(pays[key]) != 1:
            rejected.append({'race_id': key, 'reason': 'ambiguous_official_settlement'})
            continue
        pay = pays[key][0]
        pair = sorted(map(int, re.findall(r'\d+', pay['combination'])))
        require(pair == sorted(ranks[key]) and int(pay['payout']) > 0, 'official_result_mismatch')
        accepted[key] = {'pair': [f'{h:02d}' for h in pair], 'payout': int(pay['payout'])}
    return accepted, rejected


def additional(values, accepted, canonical, folder):
    """全時点の固定選択を実点数で精算し、結果待ちを別保存する。"""
    cells = {timing + '_' + name: [] for timing in ('t_minus_30m', 't_minus_10m', 't_minus_2m') for name in ('P01', 'A', 'A2', 'A3')}
    pending, mismatches = [], []
    finishers = {}
    for entry in canonical['result_entries']:
        if entry['rank'] is not None and int(entry['rank']) > 0:
            finishers.setdefault(entry['race_id'], set()).add(f"{int(entry['horse_no']):02d}")
    for f in sorted(values, key=lambda f: (f['race_id'], f['timing'])):
        outcome = accepted.get(f['race_id'])
        if outcome is None:
            pending.append({'race_id': f['race_id'], 'timing': f['timing'], 'choices': f['choices']})
            continue
        missing = sorted(finishers.get(f['race_id'], set()) - set(f['horses']))
        pairs = list(combinations(f['horses'], 2))
        winner = pairs.index(tuple(outcome['pair'])) if tuple(outcome['pair']) in pairs else -1
        if missing:
            mismatches.append({'race_id': f['race_id'], 'timing': f['timing'], 'missing_official_finishers': missing,
                               'winner_outside_saved_roster': winner == -1, 'fixed_tickets_still_settled': True})
        for name, selected in f['choices'].items():
            cells[f['timing'] + '_' + name].append(policy.settle(f, selected, outcome['payout'], winner))
    save(folder / 'additional-rows.json', cells)
    save(folder / 'pending.json', pending)
    save(folder / 'roster-mismatches.json', mismatches)
    return cells


def historical(folder):
    """年別の保存確率で同じA/A2/A3を比較し、元A結果も照合する。"""
    records, later, d0 = prior.old.reuse.load_inputs(folder)
    records = [r for r in records + later if r['race_date'] >= '2023-01-01']
    prices = prior.old.prices_for(records, folder)
    cells = {label + '_' + name: [] for label in ('S0', 'D0') for name in ('A', 'A2', 'A3')}
    dev = {key: [] for key in cells}
    for year in (2023, 2024, 2025, 2026):
        test = [r for r in records if r['race_date'].startswith(str(year))]
        ps = joblib.load(prior.old.S0 / f'{year}_S0_predictions.joblib')
        require(prior.read(prior.old.S0 / f'{year}_S0.json')['test_ids'] == [r['race_id'] for r in test], 'historical_ids')
        for r, p0 in zip(test, ps, strict=True):
            price = prices[r['race_id']]
            for label, p in (('S0', p0), ('D0', d0[r['race_id']])):
                choices = policy.select(p, price['odds'])
                for name in ('A', 'A2', 'A3'):
                    (dev if year == 2023 else cells)[label + '_' + name].append(policy.settle(r, choices[name], price['payout'], r['winner']))
    save(folder / 'historical-rows.json', cells)
    save(folder / 'development-rows.json', dev)
    return cells, dev


def run(folder, frozen_results=None):
    """原本固定→全時点選択→結果回収→期間比較まで行い採否を保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'freeze'
    try:
        initial = sources()
        frozen = read(PREVIOUS / 'manifest.json')['frozen_inputs_sha256']
        frozen |= {str((PREVIOUS / n).relative_to(ROOT)): sha(PREVIOUS / n) for n in ('additional-forecasts.json', 'assessment.json', 'independent-verification.json')}
        require(all(sha(ROOT / p) == v for p, v in frozen.items()), 'operability_input_sha')
        save(folder / 'protocol.json', {'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'seed': 450, 'bootstrap': 20000, 'new_fits': 0, 'purchase_allowed': False, 'unknown_test': False})
        stage = 'forecasts_before_results'
        values = forecasts(folder)
        stage = 'official_result_collection'
        if frozen_results is None:
            canonical = collect(folder, values)
        else:
            canonical = read(frozen_results)
            save(folder / 'canonical-results.json', canonical)
            save(folder / 'reused-results.json', {'path': str(frozen_results), 'sha256': sha(frozen_results),
                                                  'new_result_requests': 0})
        accepted, rejected = outcomes(canonical)
        save(folder / 'official-outcomes.json', accepted)
        save(folder / 'excluded-results.json', rejected)
        stage = 'assessment'
        new = additional(values, accepted, canonical, folder)
        hist, dev = historical(folder)
        assessment = {'additional': policy.assess(new, historical=False), 'historical': policy.assess(hist, historical=True),
                      'development': {k: policy.summary(v) for k, v in dev.items()},
                      'input_quality': {'roster_mismatch_observations': len(read(folder / 'roster-mismatches.json')),
                                        'purchase_eligible': not read(folder / 'roster-mismatches.json')},
                      'new_fits': 0, 'unknown_test': False, 'purchase_allowed': False}
        save(folder / 'assessment.json', assessment)
        require(sources() == initial and all(sha(ROOT / p) == v for p, v in frozen.items()), 'operability_changed')
        save(folder / 'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        print(json.dumps({g: {k: (v['total']['tickets'], v['total']['roi_percent'], v['decision']['label']) for k, v in assessment[g].items()}
                          for g in ('historical', 'additional')}), flush=True)
    except Exception as error:
        save(folder / 'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', str(error))})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/purchase_operability_20261107')
    parser.add_argument('--frozen-results', type=Path)
    args = parser.parse_args()
    run(args.output, args.frozen_results)
