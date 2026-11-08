"""概要: 統合V110採否を全元予測との照合と別の開催日再抽出で確認する。
作成日: 2026-10-24
入力: v110_final_assessment_20261024、旧/追加年代の予測。
出力: independent-verification.json。正常0、不一致時は例外停止。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_v110_final_20261024.py
注意事項: 学習・外部通信・本番変更なし。既存結果を上書きしない。
"""

from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def main():
    """全選択・集計・主区間・用途別ゲートを別集計で確認する。"""
    folder = Path('artifacts/jra_research/v110_final_assessment_20261024')
    assessment = json.loads((folder/'assessment.json').read_text('utf-8'))
    ledger = json.loads((folder/'compact-ledger.json').read_text('utf-8'))
    lookup = {(r['race_id'], r['policy']): r for r in ledger}
    assert len(lookup) == len(ledger)
    checked = 0
    for name, digest in assessment['source_sha256'].items():
        path = Path(name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                r = json.loads(line)
                best = max(range(r['pair_count']), key=r['probability'].__getitem__)
                indexes = [(r['model']+'_top1', best)]
                if r['model'] == 'V110':
                    indexes.append(('V110_original', r['chosen']))
                for policy, index in indexes:
                    actual = lookup[(r['race_id'], policy)]
                    assert actual['index'] == index
                    assert actual['selected'] == (index is not None)
                    assert actual['payout'] == (r['payout_per_100'][index]*6 if index is not None else 0)
                    assert actual['hit'] == int(actual['payout'] > 0)
                    assert actual['p'] == (r['probability'][index] if index is not None else None)
                    assert actual['loss'] == r['loss'] and actual['brier'] == r['brier']
                    checked += 1
    assert checked == len(ledger)
    checks = 0
    for scope, methods in assessment['summaries'].items():
        rows = [r for r in ledger if scope == 'all_2021_2025' or
                (r['date'][:4] in ('2024', '2025') if scope == 'primary_2024_2025' else r['date'][:4] == scope)]
        for method in ('V110_original', 'V110_top1', 'M0_top1', 'PL_top1'):
            values = [r for r in rows if r['policy'] == method]
            selected = [r for r in values if r['selected']]
            actual = methods[method]
            assert actual['races'] == len(values) and actual['selections'] == len(selected)
            assert actual['hits'] == sum(r['hit'] for r in selected)
            assert actual['stake_yen'] == len(selected)*600
            assert actual['payout_yen'] == sum(r['payout'] for r in selected)
            assert actual['profit_yen'] == actual['payout_yen']-actual['stake_yen']
            assert math.isclose(actual['logloss'], math.fsum(r['loss'] for r in values)/len(values), abs_tol=1e-12)
            checks += 1
        assert math.isclose(methods['V110_top1_minus_M0_top1'], methods['V110_top1']['hit_rate']-methods['M0_top1']['hit_rate'], abs_tol=1e-12)
    primary = assessment['summaries']['primary_2024_2025']
    daily = defaultdict(lambda: np.zeros(4))
    for r in ledger:
        if r['date'][:4] not in ('2024', '2025'):
            continue
        a = daily[r['date']]
        if r['policy'] == 'V110_top1':
            a[0] += r['hit']
            a[1] += 1
        elif r['policy'] == 'M0_top1':
            a[0] -= r['hit']
        elif r['policy'] == 'V110_original' and r['selected']:
            a[2] += 600
            a[3] += r['payout']
    a = np.array([daily[d] for d in sorted(daily)])
    rng = np.random.default_rng(340)
    differences, rois = [], []
    for _ in range(20000):
        total = a[rng.integers(0, len(a), len(a))].sum(axis=0)
        differences.append(total[0]/total[1])
        if total[2]:
            rois.append(total[3]/total[2])
    assert np.allclose(np.quantile(differences, [.025, .975]), primary['intervals']['V110_top1_minus_M0_top1_ci95'], rtol=0, atol=1e-12)
    assert np.allclose(np.quantile(rois, [.025, .975]), primary['intervals']['V110_original_roi_ci95'], rtol=0, atol=1e-12)
    gates = assessment['accuracy_gates']
    assert gates['pooled_gain_at_least_2pp'] == (primary['V110_top1_minus_M0_top1'] >= .02)
    assert gates['pooled_difference_ci_lower_above_zero'] == (min(primary['intervals']['V110_top1_minus_M0_top1_ci95']) > 0)
    assert gates['positive_hit_gain_in_both_years'] == all(assessment['summaries'][str(y)]['V110_top1_minus_M0_top1'] > 0 for y in (2024, 2025))
    assert gates['logloss_improves_both_years'] == all(assessment['summaries'][str(y)]['V110_top1']['logloss'] < assessment['summaries'][str(y)]['M0_top1']['logloss'] for y in (2024, 2025))
    assert assessment['accuracy_research_candidate_passed'] == all(gates.values())
    assert assessment['original_purchase_candidate_passed'] == all(assessment['profit_gates'].values())
    assert assessment['production_adoption'] is False
    value = {'status': 'passed', 'ledger_rows_checked': checked, 'summary_checks': checks,
             'independent_primary_bootstrap_checks': 2, 'fixed_gate_checks': 'passed',
             'input_sha256_unchanged': True, 'production_adoption': False}
    with (folder/'independent-verification.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(value))


if __name__ == '__main__':
    main()
