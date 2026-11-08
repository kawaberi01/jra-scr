"""概要: S0を固定4期間で学習し、D0・市場と比較し保存原本でも推論する。
作成日: 2026-10-25
入力: spec425、検算済み既存dataset・保存予測・公式精算・事前情報原本。
出力: 新規run内の4モデル、全確率、精度/回収率、原本互換検査、SHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_current_attributes.py
注意事項: SQL/HTTP/過去追加取得/購入/既定変更なし。過去参照済みの研究。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gc
import gzip
import json
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_course_chimera as reuse
from jra_srb import jra_research_current_attributes as model
from jra_srb.jra_research_contracts import ResearchError

ROOT, REFERENCE = reuse.ROOT, reuse.REFERENCE
read, save, sha, require, log = reuse.read, reuse.save, reuse.sha, reuse.require, reuse.log
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/425-S0市場当日属性モデルの固定検証.md'
CAPTURE = ROOT/'artifacts/jra_research/forward_capture_20261025_v4'
OUTCOMES = ROOT/'artifacts/jra_research/d0_usability_20261025_v2/official-outcomes.json'


def sources():
    """学習前後で固定する仕様・実装・再利用コードを列挙する。"""
    return {**read(REFERENCE/'model-manifest.json')['source_sha256'],
            **{str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(model.__file__),
               Path(reuse.__file__), ROOT/'scripts/verify_jra_current_attributes.py')}}


def summary(rows):
    """等競走重みの精度と100円固定1点精算を集計する。"""
    result = reuse.helper.summary(rows)
    paid = sum(r['paid_yen'] for r in rows)
    return {**result, 'stake_yen': len(rows)*100, 'paid_yen': paid,
            'net_yen': paid-len(rows)*100, 'roi_percent': paid/len(rows)}


def rows_for(records, probabilities, label, outcomes):
    """検算済み精算を正解ペアと照合し、同一レースの比較行を作る。"""
    rows = reuse.metrics(records, probabilities, label)
    for r, row, p in zip(records, rows, probabilities, strict=True):
        if r['race_date'] < '2024-01-01':
            payout = int(r['payout_yen'])
        else:
            outcome = outcomes[r['race_id']]
            a, b = model.core.base.pairs(len(r['horses']))[r['winner']]
            require(sorted([int(r['horses'][a]), int(r['horses'][b])]) == sorted(outcome['winner_pair']), 'S0_outcome_pair')
            payout = int(outcome['payout_per_100_yen'])
            if 'payout_yen' in r:
                require(payout == r['payout_yen'], 'S0_outcome_payout')
        row['top_pair_index'] = int(np.argmax(p))
        row['paid_yen'] = payout*row['hit']
    return rows


def run(folder):
    """最大4fitを逐次実行し、比較と原本互換性を一括保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        require(all(sha(ROOT/p) == value for p, value in initial.items()), 'S0_sources')
        require(read(CAPTURE/'verification.json')['status'] == 'passed', 'S0_capture_not_verified')
        frozen = {str(p.relative_to(ROOT)): sha(p) for p in (OUTCOMES, CAPTURE/'inputs.jsonl.gz', CAPTURE/'verification.json')}
        save(folder/'protocol.json', {'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'max_new_fits': 4, 'unknown_test': False, 'production_adoption': False})
        records, later, baselines = reuse.load_inputs(folder)
        outcomes = read(OUTCOMES)
        annual, pooled = {}, {k: [] for k in ('S0', 'D0', 'market')}
        hashes = {}
        for year in (2023, 2024, 2025, 2026):
            stage = f'fit_{year}'
            train = [model.clean(r)|{'winner': r['winner']} for r in records if r['race_date'] < f'{year}-01-01']
            test = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
            log('S0_fit_start', year=year, train=len(train), test=len(test))
            fitted = model.fit(train)
            path = folder/f'{year}_S0.joblib'
            joblib.dump(fitted, path, compress=3)
            restored = joblib.load(path)
            probabilities = [model.predict(restored, r) for r in test]
            require(np.array_equal(model.predict(fitted, model.clean(test[0])), probabilities[0]), 'S0_reload')
            joblib.dump(probabilities, folder/f'{year}_S0_predictions.joblib', compress=3)
            rows = {label: rows_for(test, pp, label, outcomes) for label, pp in
                    [('S0', probabilities), ('D0', [baselines[r['race_id']] for r in test]),
                     ('market', [r['market'] for r in test])]}
            annual[str(year)] = {key: summary(value) for key, value in rows.items()}
            hashes[path.name] = sha(path)
            save(folder/f'{year}_S0.json', {'train_ids': [r['race_id'] for r in train],
                 'test_ids': [r['race_id'] for r in test], 'model_sha256': hashes[path.name],
                 'rows': rows, 'summary': annual[str(year)]})
            if year == 2023:
                a, b = annual['2023']['S0'], annual['2023']['D0']
                chosen = a['logloss'] < b['logloss'] and a['hit_rate'] >= b['hit_rate']
                save(folder/'selection.json', {'S0_selected': chosen, 'confirmation_used': False, 'summary': annual['2023']})
            else:
                for key in pooled:
                    pooled[key].extend(rows[key])
            log('S0_fit_complete', year=year, summary=annual[str(year)])
            del train, probabilities, restored
            gc.collect()
        stage = 'assessment'
        totals = {key: summary(value) for key, value in pooled.items()}
        ci = reuse.helper.comparison_ci(pooled['S0'], pooled['D0'])
        checks = {'development_selected': chosen,
                  'loss_improvement_ci_positive': ci['loss_improvement_ci95'][0] > 0,
                  'pooled_hits_at_least_D0': totals['S0']['hit_rate'] >= totals['D0']['hit_rate'],
                  'market_loss_better_each_year': all(annual[str(y)]['S0']['logloss'] < annual[str(y)]['market']['logloss'] for y in (2024, 2025, 2026))}
        save(folder/'assessment.json', {'annual': annual, 'pooled': totals, 'vs_D0_ci': ci,
            'vs_market_ci': reuse.helper.comparison_ci(pooled['S0'], pooled['market']),
            'grouped_S0': reuse.helper.grouped(pooled['S0']), 'checks': checks,
            'promising_replacement': all(checks.values()), 'purchase_allowed': False, 'unknown_test': False})
        stage = 'capture_compatibility'
        accepted, rejected = [], []
        with gzip.open(CAPTURE/'inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                observation = json.loads(line)
                try:
                    r = model.from_capture(observation)
                    p = model.predict(fitted, r)
                    accepted.append({'observation_index': index, 'race_id': r['race_id'], 'timing': observation['timing'],
                        'decision_at': observation['decision_at'], 'horses': r['horses'], 'probabilities': p.tolist()})
                except (ResearchError, ValueError, KeyError) as error:
                    rejected.append({'observation_index': index, 'race_id': observation['race_id'],
                                     'reason': getattr(error, 'reason', type(error).__name__)})
        save(folder/'capture-replay.json', {'accepted': accepted, 'rejected': rejected,
             'accepted_races': len({r['race_id'] for r in accepted}), 'performance_test': False, 'live_prediction_saved': False})
        require(sources() == initial and all(sha(ROOT/p) == v for p, v in initial.items())
                and all(sha(ROOT/p) == v for p, v in frozen.items()), 'S0_source_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
             'model_sha256': hashes, 'new_fits': 4, 'D0_refits': 0,
             'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        log('S0_complete', pooled=totals, checks=checks, capture_accepted=len(accepted), capture_rejected=len(rejected))
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/jra_research/current_attributes_S0_20261025')
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
