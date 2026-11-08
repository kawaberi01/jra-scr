"""概要: D0の4部品除去を4年境界で再学習し、全条件の比較を保存する。
作成日: 2026-10-25
入力: spec405、検算済みD0 dataset/保存分布。
出力: 新runの16モデル・全分布・教師ID・選択・条件別評価。
実行例: uv run --frozen --extra ml python scripts/run_jra_d0_ablation.py --output artifacts/jra_research/d0_ablation_20261025
注意事項: 既使用過去の探索。旧fit/SQL/HTTP/既定/予想/購入を変更しない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import defaultdict
import gc
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_course_chimera as shared
from jra_srb import jra_research_d0_ablation as model

ROOT, REFERENCE = shared.ROOT, shared.REFERENCE
read, save, sha, require, log, helper = shared.read, shared.save, shared.sha, shared.require, shared.log, shared.helper
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/405-D0部品除去再学習の固定比較.md'
ORDER = ('clock', 'opponent', 'aptitude', 'rotation')


def sources():
    """全ての再利用コードと今回の固定仕様・学習コードをSHA固定する。"""
    return {**shared.sources(), **{str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(model.__file__))}}


def cell(folder, train, test, packed, baseline, year, block):
    """1除去を学習し、再読込と結果遮断を確認して全確率と教師IDを保存する。"""
    log('ablation_fit_start', year=year, omitted=block, train=len(train), test=len(test))
    fitted = model.fit_packed(packed, train, block)
    path = folder/f'{year}_{block}.joblib'
    joblib.dump(fitted, path, compress=3)
    restored = joblib.load(path)
    probabilities = [model.predict(restored, r) for r in test]
    for i in (0, len(test)//2, len(test)-1):
        require(np.array_equal(probabilities[i], model.predict(fitted, test[i]))
            and np.array_equal(probabilities[i], model.predict(restored, {**test[i], 'winner': -1, 'payout_yen': -1})), 'ablation_reload_or_result')
    rows = shared.metrics(test, probabilities, block)
    summary = helper.summary(rows)
    joblib.dump(probabilities, folder/f'{year}_{block}_predictions.joblib', compress=3)
    save(path.with_suffix('.json'), {'year': year, 'omitted': block, 'model_sha256': sha(path),
        'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test], 'rows': rows, 'summary': summary})
    log('ablation_fit_complete', year=year, omitted=block, summary=summary, D0=helper.summary(baseline))
    return rows, sha(path)


def grouped(rows, by_id):
    """全場×芝ダート/距離帯/クラスを説明用に集計し、採用群は選ばない。"""
    groups = defaultdict(list)
    for row in rows:
        r = by_id[row['race_id']]
        prefix = f"{r['course']}:{r['surface']}"
        for key in ('cs:'+prefix, 'csd:'+prefix+':'+str(row['distance_band']), 'class:'+str(r['condition'])):
            groups[key].append(row)
    return {k: helper.summary(v) for k, v in sorted(groups.items())}


def run(folder):
    """16セルを固定実行し、2023で選んだ構成だけに更新候補ゲートを適用する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        save(folder/'protocol.json', {'source_sha256': initial, 'selection_year': 2023,
            'confirmation_years': [2024, 2025, 2026], 'omitted_columns': {k: model.omitted_columns(k) for k in ORDER},
            'max_new_fits': 16, 'unknown_test': False})
        records, later, baseline = shared.load_inputs(folder)
        by_id = {r['race_id']: r for r in records+later}
        development, annual, hashes = {}, {}, {}
        pooled = {k: [] for k in (*ORDER, 'D0', 'market')}
        chosen = None
        for year in (2023, 2024, 2025, 2026):
            stage = str(year)
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
            baseline_rows = shared.metrics(test, [baseline[r['race_id']] for r in test], 'D0')
            market_rows = shared.metrics(test, [r['market'] for r in test], 'M0')
            packed = model.base.pack(train, 'D0')
            rows_by_case = {'D0': baseline_rows, 'market': market_rows}
            for block in ORDER:
                rows, digest = cell(folder, train, test, packed, baseline_rows, year, block)
                hashes[f'{year}_{block}.joblib'] = digest
                rows_by_case[block] = rows
            del packed
            gc.collect()
            annual[str(year)] = {k: helper.summary(v) for k, v in rows_by_case.items()}
            if year == 2023:
                development = annual['2023']
                b = development['D0']
                eligible = [k for k in ORDER if development[k]['logloss'] < b['logloss']-1e-8 and development[k]['hit_rate'] >= b['hit_rate']]
                chosen = min(eligible, key=lambda k: (development[k]['logloss'], ORDER.index(k))) if eligible else 'D0'
                save(folder/'selection.json', {'chosen': chosen, 'eligible': eligible, 'development': development, 'confirmation_used': False})
                log('ablation_selection_frozen', chosen=chosen)
            else:
                for key, rows in rows_by_case.items():
                    pooled[key].extend(rows)
        comparisons = {}
        for block in ORDER:
            a, b = helper.summary(pooled[block]), helper.summary(pooled['D0'])
            ci = helper.comparison_ci(pooled[block], pooled['D0'])
            checks = {'selected_in_development': chosen == block, 'pooled_loss_better': a['logloss'] < b['logloss'],
                'loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
                'market_loss_better_each_year': all(annual[str(y)][block]['logloss'] < annual[str(y)]['market']['logloss'] for y in (2024, 2025, 2026)),
                'hit_rate_not_worse': a['hit_rate'] >= b['hit_rate']}
            comparisons[block] = {'vs_D0_ci': ci, 'checks': checks, 'promising_research_candidate': all(checks.values())}
        save(folder/'assessment.json', {'chosen': chosen, 'annual': annual,
            'pooled': {k: helper.summary(v) for k, v in pooled.items()}, 'comparisons': comparisons,
            'groups': {k: grouped(v, by_id) for k, v in pooled.items()},
            'unknown_test': False, 'production_adoption': False, 'default_model_changed': False})
        require(sources() == initial, 'ablation_source_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial, 'model_sha256': hashes,
            'new_fits': 16, 'D0_refits': 0, 'assessment_sha256': sha(folder/'assessment.json')})
        log('ablation_research_complete', chosen=chosen, comparisons=comparisons)
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
