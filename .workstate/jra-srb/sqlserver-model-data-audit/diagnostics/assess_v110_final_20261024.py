"""概要: 同一v2の2021〜2025年予測からV110の購入用途と的中率用途を固定判定する。
作成日: 2026-10-24
入力: 旧年代/追加年代の保存予測・独立検算、spec340。
出力: 新規v110_final_assessment_20261024のassessment.jsonとcompact-ledger.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/assess_v110_final_20261024.py
注意事項: 外部通信・SQL・学習・本番変更なし。事前基準を変更せず区間は探索的。
"""

from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def save(path, value):
    """UTF-8で新規JSONを排他保存する。"""
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def brief(rows):
    """仮想購入点または確率1位の的中・精算・予測校正を集計する。"""
    selected = [r for r in rows if r['selected']]
    n = len(selected)
    stake = n*600
    returned = sum(r['payout'] for r in selected)
    return {'races': len(rows), 'selections': n, 'hits': sum(r['hit'] for r in selected),
            'hit_rate': sum(r['hit'] for r in selected)/n if n else None,
            'selection_days': len({r['date'] for r in selected}),
            'mean_probability': float(np.mean([r['p'] for r in selected])) if n else None,
            'stake_yen': stake, 'payout_yen': returned, 'profit_yen': returned-stake,
            'roi': returned/stake if stake else None,
            'logloss': float(np.mean([r['loss'] for r in rows])),
            'brier': float(np.mean([r['brier'] for r in rows]))}


def intervals(rows):
    """同じ開催日抽出で的中率差・確率誤差・元購入ROIの探索区間を求める。"""
    days = sorted({r['date'] for r in rows})
    grouped = defaultdict(lambda: np.zeros(8))
    for row in rows:
        a = grouped[row['date']]
        if row['policy'] == 'V110_top1':
            a[0] += row['hit']
            a[2] += 1
            a[3] += row['p']
        elif row['policy'] == 'M0_top1':
            a[1] += row['hit']
        elif row['policy'] == 'V110_original' and row['selected']:
            a[4] += 600
            a[5] += row['payout']
            a[6] += row['hit']
            a[7] += 1
    a = np.array([grouped[d] for d in days])
    draw = np.random.default_rng(340).integers(0, len(days), (20000, len(days)))
    totals = a[draw].sum(axis=1)
    delta = (totals[:, 0]-totals[:, 1])/totals[:, 2]
    residual = (totals[:, 0]-totals[:, 3])/totals[:, 2]
    valid = totals[:, 4] > 0
    roi = totals[valid, 5]/totals[valid, 4]
    return {'days': len(days), 'draws': 20000, 'seed': 340,
            'V110_top1_minus_M0_top1_ci95': np.quantile(delta, [.025, .975]).tolist(),
            'V110_top1_actual_minus_prediction_ci95': np.quantile(residual, [.025, .975]).tolist(),
            'V110_original_roi_ci95': np.quantile(roi, [.025, .975]).tolist(),
            'V110_top1_hit_rate_ci95': np.quantile(totals[:, 0]/totals[:, 2], [.025, .975]).tolist()}


def main():
    """全結果と事前ゲートを保存し、用途別の採否を確定する。"""
    base = Path('artifacts/jra_research')
    source_paths = [base/'v110_early_tokyo_20261023', base/'v110_late_tokyo_20261024']
    output = base/'v110_final_assessment_20261024'
    spec = Path('.workstate/jra-srb/sqlserver-model-data-audit/spec/340-V110の追加年代検証と採否の終了基準.md')
    rows, hashes, ids = [], {}, set()
    for folder in source_paths:
        assert json.loads((folder/'independent-verification.json').read_text('utf-8'))['status'] == 'passed'
        path = folder/'predictions.jsonl.gz'
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                r = json.loads(line)
                key = (r['race_id'], r['model'])
                assert key not in ids
                ids.add(key)
                p = np.asarray(r['probability'])
                paid = np.asarray(r['payout_per_100'])
                policies = [(r['model']+'_top1', int(np.argmax(p)))]
                if r['model'] == 'V110':
                    policies.append(('V110_original', r['chosen']))
                for policy, index in policies:
                    rows.append({'race_id': r['race_id'], 'date': r['race_date'], 'policy': policy,
                                 'selected': index is not None, 'index': index,
                                 'pair': r['keys'][index] if index is not None else None,
                                 'p': float(p[index]) if index is not None else None,
                                 'hit': int(paid[index] > 0) if index is not None else 0,
                                 'payout': int(paid[index])*6 if index is not None else 0,
                                 'loss': r['loss'], 'brier': r['brier']})
    assert all(sum(r['policy'] == policy for r in rows) == len(ids)//3
               for policy in ('V110_top1', 'M0_top1', 'PL_top1', 'V110_original'))
    summaries = {}
    scopes = {'all_2021_2025': rows, 'primary_2024_2025': [r for r in rows if r['date'][:4] in ('2024', '2025')]}
    scopes.update({str(y): [r for r in rows if r['date'].startswith(str(y))] for y in range(2021, 2026)})
    for name, items in scopes.items():
        summaries[name] = {policy: brief([r for r in items if r['policy'] == policy])
                           for policy in ('V110_original', 'V110_top1', 'M0_top1', 'PL_top1')}
        summaries[name]['intervals'] = intervals(items)
        summaries[name]['V110_top1_minus_M0_top1'] = summaries[name]['V110_top1']['hit_rate']-summaries[name]['M0_top1']['hit_rate']
    primary = summaries['primary_2024_2025']
    accuracy_gates = {'at_least_600_races': primary['V110_top1']['races'] >= 600,
                      'at_least_60_days': primary['intervals']['days'] >= 60,
                      'pooled_gain_at_least_2pp': primary['V110_top1_minus_M0_top1'] >= .02,
                      'pooled_difference_ci_lower_above_zero': primary['intervals']['V110_top1_minus_M0_top1_ci95'][0] > 0,
                      'positive_hit_gain_in_both_years': all(summaries[str(y)]['V110_top1_minus_M0_top1'] > 0 for y in (2024, 2025)),
                      'logloss_improves_both_years': all(summaries[str(y)]['V110_top1']['logloss'] < summaries[str(y)]['M0_top1']['logloss'] for y in (2024, 2025))}
    full = summaries['all_2021_2025']
    original = full['V110_original']
    profit_gates = {'at_least_100_bets': original['selections'] >= 100,
                    'at_least_30_days': original['selection_days'] >= 30,
                    'at_least_10_hits': original['hits'] >= 10,
                    'pooled_roi_at_least_105pct': original['roi'] >= 1.05,
                    'pooled_roi_ci_lower_above_100pct': full['intervals']['V110_original_roi_ci95'][0] > 1,
                    'earlier_period_minimum_gate': json.loads((source_paths[0]/'results.json').read_text('utf-8'))['V110']['all']['minimum_gate_passed']}
    accuracy_pass = all(accuracy_gates.values())
    profit_pass = all(profit_gates.values())
    result = {'status': 'assessment_complete', 'spec_sha256': hashlib.sha256(spec.read_bytes()).hexdigest(),
              'source_sha256': hashes, 'summaries': summaries, 'accuracy_gates': accuracy_gates,
              'profit_gates': profit_gates, 'accuracy_research_candidate_passed': accuracy_pass,
              'original_purchase_candidate_passed': profit_pass,
              'accuracy_decision': 'retain_for_input_audit_only' if accuracy_pass else 'reject_current_V110_for_accuracy_use',
              'purchase_decision': 'retain_for_input_audit_only' if profit_pass else 'reject_current_original_purchase_policy',
              'decision_scope': 'Current V110, fixed purposes and saved v2 evidence; not every possible future model.',
              'is_unseen_validation': False, 'historical_publication_replay_proven': False,
              'production_adoption': False, 'additional_thresholds_searched': 0}
    output.mkdir(parents=True, exist_ok=False)
    save(output/'compact-ledger.json', rows)
    save(output/'assessment.json', result)
    print(json.dumps({'primary': primary, 'full': full, 'accuracy_gates': accuracy_gates,
                      'profit_gates': profit_gates, 'accuracy_decision': result['accuracy_decision'],
                      'purchase_decision': result['purchase_decision']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
