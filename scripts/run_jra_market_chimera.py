"""概要: 市場基準の条件別キメラを開発年で選抜し、翌2年で順次検証する。
作成日: 2026-10-24
入力: 既存15馬特徴dataset、同時点市場、spec355。
出力: 新規研究フォルダーのモデル・全分布・評価・来歴・見込み判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_market_chimera.py --output artifacts/jra_research/market_condition_chimera_20261024
注意事項: SQL/HTTP/実購入/旧モデル変更なし。既使用過去の探索であり独立未知試験ではない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gc
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_condition_chimera as prior
from jra_srb import jra_research_market_chimera as model
from jra_srb.jra_research_r1_live import require


ROOT = prior.ROOT
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/355-市場基準の条件別キメラ研鑽.md'
DATASET = ROOT/'artifacts/jra_research/condition_chimera_20261024/dataset.joblib'


def source_hashes():
    """今回の仕様と新旧の計算コードSHAを固定する。"""
    return {str(p.relative_to(ROOT)): prior.sha(p) for p in
            (SPEC, Path(__file__), Path(model.__file__), Path(model.base.__file__), prior.HELPER)}


def prepare(folder):
    """既知SHAの15馬特徴に、同じ時点の単勝PLだけを追加しSQLを再読取しない。"""
    manifest = json.loads((DATASET.parent/'dataset-manifest.json').read_text('utf-8'))
    require(prior.sha(DATASET) == manifest['sha256'], 'market_chimera_dataset_sha')
    dataset = joblib.load(DATASET)
    spec = importlib.util.spec_from_file_location('market_chimera_helper', prior.HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    markets, hashes = helper.markets(folder, end_year=2025)
    require(hashes == dataset['market_hashes'], 'market_chimera_market_input_changed')
    records = dataset['records']
    for r in records:
        market = markets[r['race_id']]
        require(r['horses'] == market['horses'] and np.array_equal(r['market'], market['market'])
                and tuple(r['horses'][i] for i in model.base.pairs(len(r['horses']))[r['winner']]) == market['winner_horses'],
                'market_chimera_input_join')
        r['pl'] = market['pl']
    joblib.dump({'protocol': model.PROTOCOL, 'records': records, 'market_hashes': hashes}, folder/'dataset.joblib', compress=3)
    prior.save(folder/'dataset-manifest.json', {'sha256': prior.sha(folder/'dataset.joblib'),
        'source_dataset': str(DATASET.relative_to(ROOT)), 'source_dataset_sha256': manifest['sha256'], 'records': len(records)})
    return records


def measure(records, fitted, label):
    """全ペア分布と同一競走の的中/損失を保存可能な行へ変換する。"""
    rows, predictions = [], []
    for r in records:
        p = r['market'] if fitted is None else model.predict(fitted, model.clean(r))
        y = r['winner']
        rows.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'label': label,
            'course': r['course'], 'surface': r['surface'], 'distance_band': model.base.distance_band(r['distance']),
            'season': model.base.season(r['race_date']), 'loss': float(-np.log(p[y])),
            'hit': int(np.argmax(p) == y), 'brier': float((p@p-2*p[y]+1)/len(p))})
        predictions.append(p.astype(np.float64))
    return rows, predictions


def fitted_cell(folder, records, before, year, case):
    """対象年より前だけで学習し、全テスト分布と訓練IDを保存する。"""
    train = [r for r in records if r['race_date'] < before]
    test = [r for r in records if r['race_date'].startswith(str(year))]
    require(len(train) >= 1000 and len(test) >= 500, 'market_chimera_empty_cell')
    prior.log('fit', case=case, year=year, train_races=len(train))
    fitted = model.fit(train, case)
    model_path = folder/f'{year}_{case}.joblib'
    joblib.dump(fitted, model_path, compress=3)
    restored = joblib.load(model_path)
    require(fitted['trained_through'] < before, 'market_chimera_training_boundary')
    rows, distributions = measure(test, restored, case)
    for index in (0, len(test)//2, len(test)-1):
        record = test[index]
        p = model.predict(fitted, model.clean(record))
        require(np.array_equal(p, distributions[index]), 'market_chimera_reload_mismatch')
        require(np.array_equal(p, model.predict(restored, {**record, 'winner': -1, 'payout_yen': -999})),
                'market_chimera_result_dependency')
    joblib.dump(distributions, folder/f'{year}_{case}_predictions.joblib', compress=3)
    prior.save(folder/f'{year}_{case}.json', {'case': case, 'year': year, 'train_races': len(train),
        'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test],
        'trained_through': fitted['trained_through'], 'model_sha256': prior.sha(model_path),
        'optimizer': fitted['optimizer'], 'summary': prior.summary(rows), 'rows': rows})
    prior.log('evaluated', case=case, year=year, **prior.summary(rows))
    gc.collect()
    return rows


def run(folder):
    """5案を2023年で固定選抜し、対照とともに2024/2025年を時系列確認する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        sources = source_hashes()
        prior.save(folder/'protocol.json', {'protocol': model.PROTOCOL, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_sha256': sources, 'cases': list(model.CASES), 'select_on': '2023', 'confirm_on': ['2024', '2025'],
            'is_unseen_test': False, 'min_context_races': 100, 'default_changed': False, 'purchase_policy': None})
        stage = 'prepare'
        records = prepare(folder)
        stage = 'development'
        development = {case: fitted_cell(folder, records, '2023-01-01', 2023, case) for case in model.CASES}
        values = {case: prior.summary(rows) for case, rows in development.items()}
        minimum = min(s['logloss'] for s in values.values())
        chosen = next(c for c in model.CASES if values[c]['logloss'] <= minimum+1e-8)
        prior.save(folder/'selection.json', {'chosen': chosen, 'development': values,
            'criterion': '2023_logloss_only_tie_simplest_1e-8', 'confirmation_used_to_select': False})
        prior.log('selection_frozen', chosen=chosen)
        stage = 'confirmation'
        measured, aggregates, markets, selected_rows, calibrated_rows = {}, {}, [], [], []
        for year in (2024, 2025):
            cases = list(dict.fromkeys(('T0', 'P0', chosen)))
            measured[str(year)] = {case: fitted_cell(folder, records, f'{year}-01-01', year, case) for case in cases}
            test = [r for r in records if r['race_date'].startswith(str(year))]
            market, _ = measure(test, None, 'M0')
            measured[str(year)]['M0'] = market
            aggregates[str(year)] = {case: prior.grouped(rows) for case, rows in measured[str(year)].items()}
            markets.extend(market)
            selected_rows.extend(measured[str(year)][chosen])
            calibrated_rows.extend(measured[str(year)]['T0'])
        interval = prior.comparison_ci(selected_rows, markets)
        control_interval = prior.comparison_ci(selected_rows, calibrated_rows)
        pooled, market_summary = prior.summary(selected_rows), prior.summary(markets)
        checks = {'market_logloss_improves_each_year': all(aggregates[str(y)][chosen]['all']['logloss'] < aggregates[str(y)]['M0']['all']['logloss'] for y in (2024, 2025)),
            'pooled_market_loss_ci_positive': interval['loss_improvement_ci95'][0] > 0,
            'not_worse_than_calibration_each_year': all(aggregates[str(y)][chosen]['all']['logloss'] <= aggregates[str(y)]['T0']['all']['logloss'] for y in (2024, 2025)),
            'hit_rate_drop_no_more_than_half_pp': pooled['hit_rate'] >= market_summary['hit_rate']-.005}
        prior.save(folder/'assessment.json', {'selected': chosen, 'development': values, 'confirmation': aggregates,
            'pooled_selected': pooled, 'pooled_market': market_summary, 'pooled_calibrated': prior.summary(calibrated_rows),
            'vs_market_ci': interval, 'vs_calibrated_ci': control_interval, 'promising_checks': checks,
            'promising_research_candidate': all(checks.values()), 'production_adoption': False,
            'unseen_test': False, 'long_distance_superiority_proven': False, 'purchase_policy_evaluated': False})
        stage = 'final_fit'
        final = model.fit(records, chosen)
        joblib.dump(final, folder/'final_model.joblib', compress=3)
        prior.save(folder/'model-manifest.json', {'protocol': model.PROTOCOL, 'model_sha256': prior.sha(folder/'final_model.joblib'),
            'selected_case': chosen, 'trained_through': final['trained_through'], 'train_races': len(records),
            'train_ids': [r['race_id'] for r in records], 'source_sha256': sources,
            'dataset_sha256': prior.sha(folder/'dataset.joblib'), 'assessment_sha256': prior.sha(folder/'assessment.json')})
        require(source_hashes() == sources, 'market_chimera_source_changed')
        prior.save(folder/'verification.json', {'status': 'passed', 'selection_frozen': True, 'reload_equal': True,
            'result_ignored': True, 'source_unchanged': True, 'model_created': True,
            'promising_research_candidate': all(checks.values()), 'production_adoption': False})
        prior.log('complete', selected=chosen, promising=all(checks.values()), checks=checks, pooled=pooled, market=market_summary)
    except Exception as error:
        prior.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
