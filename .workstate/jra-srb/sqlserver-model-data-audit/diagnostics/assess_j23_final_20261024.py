"""概要: J23の旧モデルを再利用し追加2年を学習して市場との的中率比較と採否を完了する。
作成日: 2026-10-24
入力: spec345、既存v2市場2020〜2025、固定SQL履歴2003〜2025、旧J23月別モデル。
出力: 新規artifacts/jra_research/j23_final_autumn_20261024の予測・モデル・採否・来歴。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/assess_j23_final_20261024.py
注意事項: SQLはSELECTのみ。外部取得/実購入なし。旧期間再学習0、新J23学習6回。
"""

from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sys

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'scripts'))
import backtest_j23_early_autumn_20261023 as existing

OLD = ROOT/'artifacts/jra_research/j23_early_autumn_20261023'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/345-J23の市場的中率比較と最終採否.md'
OUTPUT = ROOT/'artifacts/jra_research/j23_final_autumn_20261024'
MONTHS = [f'{y}-{m:02d}' for y in range(2021, 2026) for m in (9, 10, 11)]


def brief(rows):
    """同じ競走集合における購入または確率1位の成績を集計する。"""
    selected = [r for r in rows if r['index'] is not None]
    n = len(selected)
    returned = sum(r['payout'] for r in selected)
    return {'races': len(rows), 'selections': n, 'hits': sum(r['hit'] for r in selected),
            'hit_rate': sum(r['hit'] for r in selected)/n if n else None,
            'selection_days': len({r['date'] for r in selected}),
            'mean_probability': float(np.mean([r['p'] for r in selected])) if n else None,
            'stake_yen': n*600, 'payout_yen': returned, 'profit_yen': returned-n*600,
            'roi': returned/(n*600) if n else None,
            'logloss': float(np.mean([r['loss'] for r in rows])),
            'brier': float(np.mean([r['brier'] for r in rows]))}


def intervals(rows):
    """開催日を同時再抽出し、市場との的中差と元購入ROIの探索区間を返す。"""
    dates = sorted({r['date'] for r in rows})
    grouped = defaultdict(lambda: np.zeros(7))
    for r in rows:
        a = grouped[r['date']]
        if r['policy'] == 'J23_top1':
            a[0] += r['hit']
            a[1] += 1
            a[2] += r['p']
        elif r['policy'] == 'M0_top1':
            a[0] -= r['hit']
        elif r['policy'] == 'J23_original' and r['index'] is not None:
            a[3] += 600
            a[4] += r['payout']
            a[5] += r['hit']
            a[6] += r['p']
    a = np.array([grouped[d] for d in dates])
    draws = np.random.default_rng(345).integers(0, len(a), (20000, len(a)))
    sums = a[draws].sum(axis=1)
    mask = sums[:, 3] > 0
    return {'days': len(dates), 'draws': 20000, 'seed': 345,
            'top1_minus_market_ci95': np.quantile(sums[:, 0]/sums[:, 1], [.025, .975]).tolist(),
            'original_roi_ci95': np.quantile(sums[mask, 4]/sums[mask, 3], [.025, .975]).tolist(),
            'purchased_actual_minus_prediction_ci95': np.quantile((sums[mask, 5]-sums[mask, 6])/(sums[mask, 3]/600), [.025, .975]).tolist()}


def assess(rows):
    """事前固定した主・年・場の集計と用途別の採否を作る。"""
    scopes = {'all_2021_2025': rows, 'primary_2024_2025': [r for r in rows if r['date'][:4] in ('2024', '2025')]}
    scopes.update({str(y): [r for r in rows if r['date'].startswith(str(y))] for y in range(2021, 2026)})
    scopes.update({name: [r for r in rows if r['race_id'][8:10] == code] for name, code in [('tokyo', '05'), ('nakayama', '06')]})
    summaries = {}
    for name, values in scopes.items():
        s = {policy: brief([r for r in values if r['policy'] == policy])
             for policy in ('J23_original', 'J23_top1', 'M0_top1', 'PL_top1')}
        s['intervals'] = intervals(values)
        s['top1_minus_market'] = s['J23_top1']['hit_rate']-s['M0_top1']['hit_rate']
        summaries[name] = s
    primary = summaries['primary_2024_2025']
    accuracy_gates = {'at_least_400_races': primary['J23_top1']['races'] >= 400,
                      'at_least_40_days': primary['intervals']['days'] >= 40,
                      'pooled_gain_at_least_2pp': primary['top1_minus_market'] >= .02,
                      'difference_ci_lower_above_zero': primary['intervals']['top1_minus_market_ci95'][0] > 0,
                      'positive_gain_both_years': all(summaries[str(y)]['top1_minus_market'] > 0 for y in (2024, 2025)),
                      'logloss_improves_both_years': all(summaries[str(y)]['J23_top1']['logloss'] < summaries[str(y)]['M0_top1']['logloss'] for y in (2024, 2025))}
    full = summaries['all_2021_2025']
    original = full['J23_original']
    profit_gates = {'at_least_100_bets': original['selections'] >= 100,
                    'at_least_30_days': original['selection_days'] >= 30,
                    'at_least_10_hits': original['hits'] >= 10,
                    'roi_at_least_105pct': original['roi'] >= 1.05,
                    'roi_ci_lower_above_100pct': full['intervals']['original_roi_ci95'][0] > 1,
                    'earlier_period_minimum_gate': json.loads((OLD/'results.json').read_text('utf-8'))['J23']['all']['minimum_gate_passed']}
    return {'status': 'assessment_complete', 'spec_sha256': existing.original.sha(SPEC), 'summaries': summaries,
            'accuracy_gates': accuracy_gates, 'profit_gates': profit_gates,
            'accuracy_research_candidate_passed': all(accuracy_gates.values()),
            'original_purchase_candidate_passed': all(profit_gates.values()),
            'accuracy_decision': 'retain_for_input_audit_only' if all(accuracy_gates.values()) else 'reject_current_J23_for_accuracy_use',
            'purchase_decision': 'retain_for_input_audit_only' if all(profit_gates.values()) else 'reject_current_J23_purchase_policy',
            'historical_publication_replay_proven': False, 'is_unseen_validation': False,
            'production_adoption': False, 'thresholds_searched': 0}


def run():
    """元特徴を復元し、旧モデル9個/新モデル6個で全分布と判定を保存する。

    Raises:
        FileExistsError: 出力先が既に存在する場合。
        ResearchError: 固定入力・旧モデル・旧評価行・時系列の不整合。
    Notes:
        固定SQL履歴を読取り、新規フォルダーだけへ保存する。失敗時は理由を保存して停止する。
        旧期間は再学習しない。新期間の採否はspec345の事前基準だけで決める。
    """
    OUTPUT.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        old_protocol = json.loads((OLD/'protocol.json').read_text('utf-8'))
        for name, digest in old_protocol['source_sha256'].items():
            existing.require(existing.original.sha(ROOT/name) == digest, 'j23_original_source_changed')
        existing.save(OUTPUT/'protocol.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'spec_sha256': existing.original.sha(SPEC), 'months': MONTHS, 'train_start': '2020-01-01',
            'history_start': '2003-01-01', 'history_end': '2025-12-31',
            'source_sha256': old_protocol['source_sha256'], 'old_ledger_sha256': existing.original.sha(OLD/'ledger.json'),
            'new_fit_limit': 6, 'reuse_old_models': 9, 'production_adoption': False})
        stage = 'market_inputs'
        markets, hashes = existing.markets(OUTPUT, end_year=2025)
        stage = 'history_reconstruction'
        records = existing.prepare(OUTPUT, markets, end_year=2025)
        del markets
        existing.save(OUTPUT/'feature-pool.json', {'records': len(records), 'end_date': max(r['race_date'] for r in records)})
        old_rows = {(r['race_key'], r['model']): r for r in json.loads((OLD/'ledger.json').read_text('utf-8'))}
        (OUTPUT/'models').mkdir()
        ledger, reuse_checks, new_fits = [], 0, 0
        with gzip.open(OUTPUT/'predictions.jsonl.gz', 'wt', encoding='utf-8', newline='\n') as stream:
            for month in MONTHS:
                stage = 'month_'+month
                train = [r for r in records if '2020-01-01' <= r['race_date'] < month+'-01']
                test = [r for r in records if r['race_date'][:7] == month and r['race_key'][8:10] in ('05', '06')]
                existing.require(bool(test) and len(train) >= 100, 'j23_empty_fold')
                if month[:4] < '2024':
                    source = OLD/'cells'/f'{month}_J23.joblib'
                    cell = json.loads(source.with_suffix('.json').read_text('utf-8'))
                    existing.require(existing.original.sha(source) == cell['model_sha256'], 'j23_old_model_hash')
                    model = joblib.load(source)
                    existing.require(model['train_races'] == len(train) and model['trained_through'] == max(r['race_date'] for r in train), 'j23_old_training_changed')
                else:
                    model = existing.learner.fit(train, 'J23')
                    source = OUTPUT/'models'/f'{month}_J23.joblib'
                    joblib.dump(model, source)
                    model = joblib.load(source)
                    new_fits += 1
                existing.require(model['trained_through'] < month+'-01', 'j23_future_teacher')
                existing.save(OUTPUT/'models'/f'{month}_J23.json', {'month': month, 'model_path': str(source.relative_to(ROOT)),
                    'model_sha256': existing.original.sha(source), 'train_races': len(train),
                    'trained_through': model['trained_through'], 'training_race_ids': [r['race_key'] for r in train],
                    'test_races': len(test), 'reused': month[:4] < '2024'})
                for record in test:
                    with threadpool_limits(limits=1):
                        p = existing.learner.predict(model, existing.learner.clean_record(record))
                    measured = existing.original.measure(record, p)
                    measured.update(model='J23', month=month)
                    if month[:4] < '2024':
                        existing.require(measured == old_rows[(record['race_key'], 'J23')], 'j23_old_measure_changed')
                        reuse_checks += 1
                    for policy, index, distribution in [('J23_original', measured['chosen'], p),
                                                       ('J23_top1', int(np.argmax(p)), p),
                                                       ('M0_top1', int(np.argmax(record['market'])), record['market']),
                                                       ('PL_top1', int(np.argmax(record['pl'])), record['pl'])]:
                        ledger.append({'race_id': record['race_key'], 'date': record['race_date'], 'policy': policy,
                            'index': index, 'p': float(distribution[index]) if index is not None else None,
                            'hit': int(index == record['winner']),
                            'payout': int(record['payout_yen'])*6 if index == record['winner'] else 0,
                            'loss': float(-np.log(distribution[record['winner']])),
                            'brier': float((distribution@distribution-2*distribution[record['winner']]+1)/len(distribution))})
                    stream.write(json.dumps({'race_id': record['race_key'], 'date': record['race_date'], 'month': month,
                        'horses': record['horses'], 'x': record['x'].tolist(), 'market': record['market'].tolist(),
                        'pl': record['pl'].tolist(), 'prices': record['prices'].tolist(), 'probability': p.tolist(),
                        'winner': int(record['winner']), 'payout_per_100': int(record['payout_yen']),
                        'chosen': measured['chosen']}, ensure_ascii=False, allow_nan=False)+'\n')
                for index in sorted({0, len(test)//2, len(test)-1}):
                    record = test[index]
                    clean = existing.learner.clean_record(record)
                    mutated = existing.learner.clean_record({**record, 'winner': 999, 'payout_yen': 999999})
                    with threadpool_limits(limits=1):
                        existing.require(np.array_equal(existing.learner.predict(model, clean), existing.learner.predict(model, mutated)), 'j23_result_dependency')
                print(json.dumps({'stage': 'evaluated', 'month': month, 'reused': month[:4] < '2024',
                                  'train_races': len(train), 'test_races': len(test)}), flush=True)
        existing.require(reuse_checks == 805 and new_fits == 6, 'j23_incomplete_comparison')
        stage = 'assessment'
        result = assess(ledger)
        for name, digest in hashes.items():
            existing.require(existing.original.sha(ROOT/name) == digest, 'j23_input_changed')
        existing.save(OUTPUT/'compact-ledger.json', ledger)
        existing.save(OUTPUT/'assessment.json', result)
        existing.save(OUTPUT/'verification.json', {'status': 'passed', 'old_measures_matched': reuse_checks,
            'new_fits': new_fits, 'future_teacher_rows': 0, 'input_sha256_unchanged': True,
            'production_adoption': False})
        print(json.dumps({'status': 'complete', 'primary': result['summaries']['primary_2024_2025'],
                          'full': result['summaries']['all_2021_2025'], 'accuracy_gates': result['accuracy_gates'],
                          'profit_gates': result['profit_gates'], 'accuracy_decision': result['accuracy_decision'],
                          'purchase_decision': result['purchase_decision']}, ensure_ascii=False), flush=True)
    except Exception as error:
        existing.save(OUTPUT/'failure.json', {'stage': stage, 'type': type(error).__name__,
            'reason': error.reason if isinstance(error, existing.ResearchError) else str(error)[:300]})
        raise


if __name__ == '__main__':
    run()
