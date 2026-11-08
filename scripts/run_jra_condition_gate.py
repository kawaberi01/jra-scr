"""概要: 条件制限20案と同時点合議5案を逐次比較し、当日事前実績も監査する。
作成日: 2026-11-07
入力: spec454、固定S0/M10等の保存確率・価格・結果、shadow原本。
出力: 新規runの全選択、年別証跡、27セル採否、本日監査、SHA台帳。
実行例: uv run --frozen --extra ml python scripts/run_jra_condition_gate.py
注意事項: 0fit、SQL/HTTP書込・実購入・設定変更なし。既使用過去の研究。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import datetime
from itertools import combinations
from pathlib import Path

import joblib
import numpy as np

import run_jra_ten_minute as reuse
from jra_srb import jra_research_condition_gate as gate
from jra_srb import jra_research_purchase_portfolio as policy

ROOT, read, save, sha, require = reuse.ROOT, reuse.read, reuse.save, reuse.sha, reuse.require
T10 = ROOT / 'artifacts/jra_research/ten_minute_20261107'
S0 = ROOT / 'artifacts/jra_research/purchase_filters_20261107'
SHADOW = ROOT / 'artifacts/jra_research/shadow_sessions_20261107_v3'
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/454-条件制限の時系列再検証と継続運用.md'
CONSENSUS = ('top1', 'top3', 'S0_ev', 'S10_ev', 'both_ev')


def shadow_file(name):
    """移行元を含む保存済み原本を探し、複数存在時は同一SHAを要求する。"""
    paths = [p for p in (SHADOW / name, SHADOW.parent / 'shadow_sessions_20261107_v2' / name) if p.exists()]
    require(paths and len({sha(p) for p in paths}) == 1, 'gate_shadow_original_missing_or_changed')
    return paths[0]


def audit_shadow(folder):
    """全事前予想・受領・読戻し・公式仮想払戻を照合し、見送り理由も集計する。"""
    state = read(SHADOW / 'state.json')
    require(state['status'] == 'finished' and not state['errors'], 'gate_shadow_not_finished')
    rows, frozen = [], {str((SHADOW / 'state.json').relative_to(ROOT)): sha(SHADOW / 'state.json')}
    for pid, item in state['records'].items():
        paths = [shadow_file(pid + '-payload.json'), shadow_file(pid + '-readback.json'),
                 shadow_file(item['evaluation_id'] + '-readback.json')]
        payload, actual, evaluated = map(read, paths)
        frozen.update({str(p.relative_to(ROOT)): sha(p) for p in paths})
        require(item['status'] == 'evaluated' and payload['prediction_id'] == actual['prediction_id'] == evaluated['prediction_id'] == pid,
                'gate_shadow_identity')
        forecast, snap = payload['prediction_json'], payload['pre_race_snapshot']
        require(actual['prediction'] == forecast and actual['pre_race_snapshot'] == snap, 'gate_shadow_prediction_readback')
        require(payload['budget'] == actual['budget'] == evaluated['total_bet'] == 0
                and payload['prediction_tickets'] == actual['prediction_tickets'] == [], 'gate_actual_purchase')
        post = datetime.fromisoformat(item['post_at'])
        require(datetime.fromisoformat(item['server_received_at']) < post
                and datetime.fromisoformat(payload['created_at']) < post
                and forecast['generated_before_result'] and not forecast['reconstruction_after_result'], 'gate_not_prerace')
        ranking = forecast['pair_ranking']
        p = np.asarray([r['probability'] for r in ranking]); o = np.asarray([r['odds'] for r in ranking])
        selected = policy.select(p, o)[item['rule']]
        plan = forecast['research_plan']
        require(plan['total_stake_yen'] == item['virtual_stake_yen'] == 100 * len(selected), 'gate_shadow_policy')
        if selected:
            require(sorted(map(int, plan['tickets'][0]['selection'])) == sorted(map(int, ranking[selected[0]]['horses'])), 'gate_shadow_pair')
        ev = evaluated['evaluation']
        official = {tuple(sorted(map(int, r['combination'].split('-')))): int(r['payout'])
                    for r in ev['payouts'] if r['bet_type'] in ('quinella', '馬連')}
        pair = tuple(sorted(map(int, ranking[selected[0]]['horses']))) if selected else None
        paid = official.get(pair, 0) if selected else 0
        sim = ev['summary']['research_simulation']
        require(not selected or sim == item['research_simulation'], 'gate_shadow_simulation_readback')
        require(not selected or (sim['virtual_payout_yen'] == paid and sim['virtual_stake_yen'] == 100), 'gate_shadow_official_payout')
        row = {'race_id': item['race_id'], 'race_date': snap['race_date'], 'model': item['case'],
               'indices': selected, 'tickets': len(selected), 'stake_yen': 100 * len(selected),
               'paid_yen': paid, 'hits': int(paid > 0), 'official_payout_yen': next(iter(official.values()), 0),
               'max_ev': float(max(p * o)), 'top_probability_ev': float(p[np.argmax(p)] * o[np.argmax(p)]),
               'A_eligible_count': int(np.sum((p >= .03) & (o >= 4) & (o <= 20) & (p * o >= 1.05))),
               'server_received_at': item['server_received_at'], 'post_at': item['post_at']}
        rows.append(row)
    summary = {case: policy.summary([r for r in rows if r['model'] == case]) for case in ('S0', 'M10')}
    save(folder / 'prospective-rows.json', rows)
    save(folder / 'prospective-assessment.json', {'date': '2026-11-07', 'models': summary,
         'audited_predictions': len(rows), 'actual_purchase_yen': 0, 'enough_for_profit_adoption': False})
    return frozen


def inputs(folder):
    """検算済み原本SHAを確認し、固定候補とT10合議を結果非依存で再構築する。"""
    frozen = {}
    paths = [S0 / 'selected-rows.json', S0 / 'independent-verification.json', T10 / 'dataset.joblib',
             T10 / 'purchase-rows.json', T10 / 'independent-verification-v2.json']
    for parent in (S0, T10):
        require(read(parent / ('independent-verification.json' if parent == S0 else 'independent-verification-v2.json'))['status'] == 'passed', 'gate_unverified_source')
    for parent, names in ((S0, ['selected-rows.json']), (T10, ['dataset.joblib', 'purchase-rows.json'])):
        manifest = read(parent / 'manifest.json')['files_sha256']
        require(all(sha(parent / n) == manifest[n] for n in names), 'gate_source_manifest')
    s0 = []
    for r in read(S0 / 'selected-rows.json')['S0']:
        buy = r['ev'] >= 1
        s0.append({k: r[k] for k in ('race_id', 'race_date', 'course', 'surface', 'distance')} |
                  {'indices': [r['top_pair_index']] if buy else [], 'tickets': int(buy),
                   'stake_yen': 100 * int(buy), 'paid_yen': r['paid_yen'] if buy else 0,
                   'hits': r['hit'] if buy else 0, 'official_payout_yen': r['official_payout_yen']})
    records = joblib.load(T10 / 'dataset.joblib')
    m10, consensus = [], {name: [] for name in CONSENSUS}
    for year in (2023, 2024, 2025, 2026):
        test = [r for r in records if r['race_date'].startswith(str(year))]
        pp = {}
        for case in ('M10', 'S10', 'S0_direct'):
            path = T10 / f'{year}_{case}_predictions.joblib'
            require(sha(path) == read(T10 / 'manifest.json')['files_sha256'][path.name], 'gate_prediction_sha')
            paths.append(path)
            pp[case] = joblib.load(path)
            require(len(pp[case]) == len(test), 'gate_probability_count')
        metadata = read(T10 / f'{year}_M10.json'); paths.append(T10 / f'{year}_M10.json')
        require(metadata['test_ids'] == [r['race_id'] for r in test]
                and all(key[:4] < str(year) for key in metadata['train_ids']), 'gate_model_year_boundary')
        for pos, r in enumerate(test):
            chosen = policy.select(pp['M10'][pos], r['prices'])['A']
            row = policy.settle(r, chosen, r['payout_yen'], r['winner']) | {
                k: int(r[k]) for k in ('course', 'surface', 'distance')}
            m10.append(row)
            idx = chosen[0] if chosen else None
            direct, same = pp['S0_direct'][pos], pp['S10'][pos]
            rank = int(np.sum(direct > direct[idx])) + 1 if chosen else None
            masks = {'top1': bool(chosen and idx == int(np.argmax(direct))),
                     'top3': bool(chosen and rank <= 3),
                     'S0_ev': bool(chosen and direct[idx] * r['prices'][idx] >= 1),
                     'S10_ev': bool(chosen and same[idx] * r['prices'][idx] >= 1)}
            masks['both_ev'] = masks['S0_ev'] and masks['S10_ev']
            for name in CONSENSUS:
                consensus[name].append(row if masks[name] else row | {'indices': [], 'tickets': 0, 'hits': 0, 'stake_yen': 0, 'paid_yen': 0})
    original = read(T10 / 'purchase-rows.json')['M10_A']
    require([{k: r[k] for k in original[0]} for r in m10 if r['race_date'] >= '2024-01-01'] == original, 'gate_M10_replay_changed')
    frozen.update({str(p.relative_to(ROOT)): sha(p) for p in paths})
    save(folder / 'base-rows.json', {'S0_P01': s0, 'M10_A': m10})
    save(folder / 'consensus-rows.json', consensus)
    return {'S0_P01': s0, 'M10_A': m10}, consensus, frozen


def diagnostic_groups(base):
    """全群の記述統計を残し、成績が良い群だけを報告対象にしない。"""
    out = {}
    for case, rows in base.items():
        out[case] = {}
        for dimension in gate.DIMENSIONS:
            keys = sorted({gate.group_key(r, dimension) for r in rows})
            out[case][dimension] = {key: {
                str(year): policy.summary([r for r in rows if r['race_date'].startswith(str(year)) and gate.group_key(r, dimension) == key])
                for year in (2023, 2024, 2025, 2026)} for key in keys}
    return out


def run(folder):
    """事前仕様を固定して3段階を実行し、失敗時も新runへ証跡を残す。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'freeze'
    try:
        sources = {str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(gate.__file__),
                   Path(policy.__file__), ROOT / 'scripts/verify_jra_condition_gate.py', ROOT / 'tests/test_jra_condition_gate.py')}
        save(folder / 'protocol.json', {'source_sha256': sources, 'dimensions': list(gate.DIMENSIONS),
             'variants': ['pooled', 'annual_stable'], 'consensus': list(CONSENSUS), 'family_cells': 27,
             'new_fits': 0, 'unknown_test': False, 'purchase_allowed': False})
        stage = 'prospective_audit'
        frozen = audit_shadow(folder)
        stage = 'input_and_consensus'
        base, consensus, hist = inputs(folder); frozen.update(hist)
        cells, audit = {}, {}
        for case, rows in base.items():
            cells[case + '_control'] = [r for r in rows if r['race_date'] >= '2024-01-01']
            for dimension in gate.DIMENSIONS:
                for stable in (False, True):
                    name = case + '_' + dimension + ('_stable' if stable else '_pooled')
                    cells[name], audit[name] = gate.walk_forward(rows, dimension, stable)
        for name, rows in consensus.items():
            cells['M10_consensus_' + name] = [r for r in rows if r['race_date'] >= '2024-01-01']
        require(len(cells) == 27, 'gate_family_count')
        save(folder / 'selection-audit.json', audit)
        save(folder / 'settlement-rows.json', cells)
        save(folder / 'all-group-diagnostics.json', diagnostic_groups(base))
        stage = 'assessment'
        assessed = policy.assess(cells, historical=True)
        save(folder / 'assessment.json', assessed)
        save(folder / 'decision.json', {'promising_cells': [k for k, v in assessed.items() if v['decision']['label'] == 'promising_historical_candidate'],
             'unknown_test': False, 'purchase_allowed': False, 'new_fits': 0,
             'cohort_note': 'S0 uses T30 original cohort; M10/consensus use T10 complete cohort. No causal cross-time comparison.'})
        require(all(sha(ROOT / p) == h for p, h in (sources | frozen).items()), 'gate_sources_changed')
        save(folder / 'manifest.json', {'status': 'complete', 'source_sha256': sources, 'frozen_inputs_sha256': frozen,
             'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        print('complete', [(k, v['total']['tickets'], round(v['total']['roi_percent'] or 0, 3), v['decision']['label']) for k, v in assessed.items()], flush=True)
    except Exception as error:
        save(folder / 'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', str(error))})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/condition_gate_20261107')
    run(parser.parse_args().output)
