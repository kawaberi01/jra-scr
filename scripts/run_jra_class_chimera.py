"""概要: 保存カードの競走条件コードを監査し、共有D0への追加効果を固定比較する。
作成日: 2026-10-25
入力: spec400、検算済みD0 dataset、2020–2026保存カード、JV SDK。
出力: 新規研究runの入力監査、4学習モデル、全分布、選択と評価。
実行例: uv run --frozen --extra ml python scripts/run_jra_class_chimera.py --output artifacts/jra_research/class_D0_20261025
注意事項: 過去公表時点未証明の探索。旧D0/予想/SQL/既定モデルを変更しない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter
import gc
import gzip
import json
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_course_chimera as shared
from jra_srb import jra_research_class_chimera as model

ROOT, REFERENCE = shared.ROOT, shared.REFERENCE
read, save, sha, require, log, helper = shared.read, shared.save, shared.sha, shared.require, shared.log, shared.helper
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/400-D0競走条件コード追加の固定比較.md'
CARDS = ROOT/'data/training/jra_o1o2_asof_v2/20261002-raw-v2-complete'
COURSES = {1:'sapporo', 2:'hakodate', 3:'fukushima', 4:'niigata', 5:'tokyo', 6:'nakayama', 7:'chukyo', 8:'kyoto', 9:'hanshin', 10:'kokura'}


def sources():
    """元D0と今回使う実装・仕様のSHAを固定する。"""
    return {**shared.sources(), **{str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(model.__file__))}}


def prepare(folder, records, later):
    """結果欄を使わず元カードを照合し、全件のコードと公表未検証状態を保存する。"""
    wanted = {r['race_id']: r for r in records+later}
    seen, hashes, coverage = set(), {}, {}
    for year in range(2020, 2027):
        path = CARDS/str(year)/'races.jsonl.gz'
        digest = sha(path)
        require(digest == read(path.parent/'manifest.json')['files']['races.jsonl.gz']['sha256'], 'class_card_sha')
        hashes[str(path.relative_to(ROOT))] = digest
        codes, statuses = Counter(), Counter()
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                source = json.loads(line)
                key = source['race_id']
                if key not in wanted:
                    continue
                r, card = wanted[key], source['race']
                require(key not in seen and card['race_date'] == r['race_date']
                    and card['course'] == COURSES[int(r['course'])] and int(card['distance']) == int(r['distance'])
                    and card['surface'] == ('turf' if int(r['surface']) == 0 else 'dirt'), 'class_card_join')
                r['class_code'] = model.normalize_code(card.get('condition_code'))
                require(r['class_code'] == model.normalize_code(r.get('condition')), 'class_existing_raw_code_mismatch')
                codes[r['class_code']] += 1
                statuses[card.get('metadata_asof_status', 'missing')] += 1
                seen.add(key)
        coverage[str(year)] = {'codes': dict(codes), 'metadata_asof_status': dict(statuses)}
    require(seen == set(wanted), 'class_missing_card')
    sdk = list(Path('D:/develop/jra-van-data/tools/jra-van-sdk').rglob('JVData_Struct.cs'))
    require(len(sdk) == 1 and sha(sdk[0]) == '605057bb211eb6a94056a54496f3dd30f864ac2ad140fcfc8840ac8a6ed9e4fe', 'class_sdk_contract')
    joblib.dump({'records': records, 'later': later}, folder/'dataset.joblib', compress=3)
    save(folder/'class-input-manifest.json', {'card_sha256': hashes, 'coverage': coverage, 'races': len(seen),
        'dataset_sha256': sha(folder/'dataset.joblib'), 'sdk_sha256': sha(sdk[0]),
        'field': 'JV_RA_RACE.JyokenInfo.JyokenCD[4]; one-based 635..637; zero-based 634:637',
        'code_table': '2007 競走条件コード; 005=1勝,010=2勝,016=3勝,701=新馬,702=未出走,703=未勝利,999=オープン; other valid 3-digit categories retained',
        'historical_publication_verified': False, 'grade_age_sex_eligibility_added': False})


def cell(folder, records, later, baselines, year):
    """前年末までの教師でBCを学習し、同一競走の共有D0と比較する。"""
    train = [r for r in records if r['race_date'] < f'{year}-01-01']
    test = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
    log('class_fit_start', year=year, train=len(train), test=len(test))
    fitted = model.fit(train)
    path = folder/f'{year}_BC.joblib'
    joblib.dump(fitted, path, compress=3)
    restored = joblib.load(path)
    probabilities = [model.predict(restored, r) for r in test]
    for i in (0, len(test)//2, len(test)-1):
        require(np.array_equal(model.predict(fitted, test[i]), probabilities[i]) and np.array_equal(
            model.predict(restored, {**test[i], 'winner': -1, 'payout_yen': -1}), probabilities[i]), 'class_reload_or_result')
    rows = {'BC': shared.metrics(test, probabilities, 'BC'),
        'D0': shared.metrics(test, [baselines[r['race_id']] for r in test], 'D0'),
        'market': shared.metrics(test, [r['market'] for r in test], 'M0')}
    joblib.dump(probabilities, folder/f'{year}_BC_predictions.joblib', compress=3)
    save(folder/f'{year}_BC.json', {'year': year, 'model_sha256': sha(path),
        'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test],
        'rows': rows, 'summary': {k: helper.summary(v) for k, v in rows.items()}})
    log('class_fit_complete', year=year, summary={k: helper.summary(v) for k, v in rows.items()})
    gc.collect()
    return rows


def run(folder):
    """2023だけで選択し、固定した基準で後年の追加価値を判定する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        save(folder/'protocol.json', {'source_sha256': initial, 'selection_year': 2023,
            'confirmation_years': [2024, 2025, 2026], 'max_new_fits': 4, 'unknown_test': False})
        records, later, baselines = shared.load_inputs(folder)
        prepare(folder, records, later)
        stage = 'development'
        dev = cell(folder, records, later, baselines, 2023)
        a, b = helper.summary(dev['BC']), helper.summary(dev['D0'])
        chosen = 'BC' if a['logloss'] < b['logloss']-1e-8 and a['hit_rate'] >= b['hit_rate'] else 'D0'
        save(folder/'selection.json', {'chosen': chosen, 'development': {k: helper.summary(v) for k, v in dev.items()}, 'confirmation_used': False})
        stage = 'confirmation'
        pooled, annual = {k: [] for k in ('BC', 'D0', 'market')}, {}
        for year in (2024, 2025, 2026):
            rows = cell(folder, records, later, baselines, year)
            annual[str(year)] = {k: helper.summary(v) for k, v in rows.items()}
            for k, v in rows.items():
                pooled[k].extend(v)
        a, b = helper.summary(pooled['BC']), helper.summary(pooled['D0'])
        ci = helper.comparison_ci(pooled['BC'], pooled['D0'])
        checks = {'development_selected_BC': chosen == 'BC', 'pooled_loss_better_than_D0': a['logloss'] < b['logloss'],
            'loss_improvement_ci_positive': ci['loss_improvement_ci95'][0] > 0,
            'market_loss_better_each_year': all(v['BC']['logloss'] < v['market']['logloss'] for v in annual.values()),
            'pooled_hits_not_worse_than_D0': a['hit_rate'] >= b['hit_rate']}
        save(folder/'assessment.json', {'chosen': chosen, 'annual': annual,
            'pooled': {k: helper.summary(v) for k, v in pooled.items()}, 'vs_D0_ci': ci, 'checks': checks,
            'promising_class_research_candidate': all(checks.values()), 'unknown_test': False,
            'historical_publication_verified': False, 'production_adoption': False, 'default_model_changed': False})
        require(sources() == initial, 'class_final_source_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial,
            'model_sha256': {f'{y}_BC.joblib': sha(folder/f'{y}_BC.joblib') for y in (2023, 2024, 2025, 2026)},
            'new_fits': 4, 'D0_refits': 0, 'assessment_sha256': sha(folder/'assessment.json')})
        log('class_research_complete', chosen=chosen, checks=checks)
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
