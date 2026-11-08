"""概要: C02の目的関数・月次時点・保存集計・原本不変を独立計算で確認する。
作成日: 2026-10-23
入力: C02保存結果、元セル/モデル、同じ診断モジュール。
出力: independent-verification.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_j23_clock_quality_20261023.py
注意事項: SQL読取・学習・原本変更なし。検証JSONは新規保存のみ。
"""

from collections import defaultdict
import json
import math

import numpy as np
from scipy.special import logsumexp

import screen_j23_clock_quality_20261023 as candidate


def independent_objective(alpha, data):
    """競走ごとのlogsumexpから損失を計算し、連結最適化の実装と比較する。"""
    boundaries = list(data['starts'])+[len(data['logp'])]
    losses = []
    for i, (begin, end) in enumerate(zip(boundaries, boundaries[1:])):
        logits = data['logp'][begin:end]+alpha*data['delta'][begin:end]
        target = data['target'][i]-begin
        losses.append(logsumexp(logits)-logits[target])
    return float(np.mean(losses)+.001*alpha**2/2)


def verify():
    """合成値で内部式を、保存値で期間・指標・ゲート・元SHAを別計算し保存する。"""
    out = candidate.OUT
    load = lambda name: json.loads((out/name).read_text(encoding='utf-8'))
    result, fits, rows, protocol = (load(n) for n in ('results.json', 'calibrations.json', 'selection-predictions.json', 'protocol.json'))
    rng = np.random.default_rng(270)
    for _ in range(10):
        sizes = [3, 7, 11]
        data = {'logp': np.concatenate([np.log(rng.dirichlet(np.ones(n))) for n in sizes]),
                'delta': rng.normal(size=sum(sizes)), 'starts': np.asarray([0, 3, 10]),
                'groups': np.repeat(np.arange(3), sizes), 'target': np.asarray([1, 5, 17])}
        alpha = candidate.fit(data)
        for a in (0., alpha, 1.):
            value, grad = candidate.objective(a, data)
            assert abs(value-independent_objective(a, data)) < 1e-12
            h = 1e-5
            numerical = (independent_objective(a+h, data)-independent_objective(a-h, data))/(2*h)
            assert abs(grad-numerical) < 1e-7
        assert independent_objective(alpha, data) <= min(independent_objective(a, data) for a in np.linspace(0, 1, 101))+1e-12
    assert len(rows) == 4938 and len(fits) == 21 and len(protocol['targets']) == 5657
    assert len({r['race_key'] for r in rows}) == len(rows)
    assert all('2024-07' <= r['race_date'][:7] <= '2026-03' for r in rows)
    for fit in fits:
        past = sorted(t['race_key'] for t in protocol['targets'] if t['race_key'][:6] < fit['month'].replace('-', ''))
        assert len(past) == fit['training_races'] and candidate.trace.digest(past) == fit['training_cohort_sha256']
        assert fit['trained_through'] < fit['month']+'-01' and 0 <= fit['alpha'] <= 1 and fit['quality_scale'] > 0
        monthly = [r for r in rows if r['race_date'][:7] == fit['month']]
        assert monthly and all(r['alpha'] == fit['alpha'] for r in monthly)
    daily = defaultdict(lambda: [0., 0])
    for r in rows:
        assert math.isclose(r['loss'], -math.log(r['winning_probability']), abs_tol=1e-12)
        daily[r['race_date']][0] += r['loss']-r['J23_loss']
        daily[r['race_date']][1] += 1
    values = np.asarray([daily[k] for k in sorted(daily)])
    indices = np.random.default_rng(260).integers(0, len(values), size=(2000, len(values)))
    totals = values[indices].sum(axis=1)
    bounds = np.quantile(totals[:, 0]/totals[:, 1], [.025, .975])
    s = result['selection']
    assert np.allclose(bounds, s['difference_95'], atol=1e-14, rtol=0)
    for key, field in (('calibrated_logloss', 'loss'), ('J23_logloss', 'J23_loss'), ('M0_logloss', 'M0_loss'),
                       ('candidate_brier', 'brier'), ('J23_brier', 'J23_brier')):
        assert abs(math.fsum(r[field] for r in rows)/len(rows)-s[key]) < 1e-12
    assert all(candidate.trace.sha(candidate.ROOT/p) == h for p, h in result['source_sha256'].items())
    assert result['selection_passed'] == all(result['gate_checks'].values())
    assert result['confirmation_fits'] == result['confirmation_predictions'] == 0
    assert candidate.trace.sha(candidate.ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec'/protocol['spec']) == protocol['spec_sha256']
    candidate.save('independent-verification.json', {'status': 'passed', 'random_objective_checks': 10,
                   'independent_logsumexp_and_gradient': True, 'grid_minimum': True,
                   'strict_prior_cohort_and_scale': True, 'saved_probability_and_metrics': True,
                   'paired_day_interval': True, 'source_and_protocol_unchanged': True,
                   'rows': len(rows), 'fits': len(fits), 'confirmation_fits': 0})
    print('independent verification passed: objective/gradient/grid/prior cohort/metrics/bootstrap/source hashes')


if __name__ == '__main__':
    verify()
