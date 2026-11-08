"""概要: H2の順位学習/市場混合5案を2023年で選び、翌3年で固定確認する。
作成日: 2026-10-24
入力: spec360、保存済み市場/15特徴/年別H2、2026派生特徴。
出力: 新規runの全分布、候補、選抜、確認、保存モデルと比較判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_rank_chimera.py --output artifacts/jra_research/market_rank_chimera_20261024
注意事項: SQL/HTTP/実購入/旧モデル変更なし。既使用過去の探索。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gc
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_market_chimera as old
from jra_srb import jra_research_rank_chimera as model


ROOT = old.ROOT
BASE = ROOT/'artifacts/jra_research/market_condition_chimera_20261024'
LATER = ROOT/'artifacts/jra_research/market_condition_2026_inputs_20261024'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/360-H2の確率と1位選択の両立検証.md'


def sources():
    """仕様と新旧の特徴/推論コードのSHAを固定する。"""
    paths = (SPEC, Path(__file__), Path(model.__file__), Path(model.core.__file__), Path(model.core.base.__file__))
    return {str(p.relative_to(ROOT)): old.prior.sha(p) for p in paths}


def read(path):
    """UTF-8の保存JSONを読む。"""
    return old.prior.features.read_json(path)


def load_reference(year):
    """既存年別H2または最終H2をSHA検証して再学習せず読む。"""
    if year == 2026:
        manifest, path = read(BASE/'model-manifest.json'), BASE/'final_model.joblib'
        expected = manifest['model_sha256']
    else:
        manifest, path = read(BASE/f'{year}_H2.json'), BASE/f'{year}_H2.joblib'
        expected = manifest['model_sha256']
    old.require(old.prior.sha(path) == expected, 'rank_reference_model_sha')
    fitted = joblib.load(path)
    old.require(fitted['trained_through'] < f'{year}-01-01', 'rank_reference_training_boundary')
    return fitted


def measure(records, fitted, label):
    """現在結果を推論から遮断し、同一競走の全分布と性能を返す。"""
    rows, probabilities = [], []
    for r in records:
        p = np.asarray(r['market']) if fitted is None else model.predict(fitted, model.core.clean(r))
        y = r['winner']
        rows.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'label': label,
            'course': r['course'], 'surface': r['surface'], 'distance_band': model.core.base.distance_band(r['distance']),
            'season': model.core.base.season(r['race_date']), 'loss': float(-np.log(p[y])), 'hit': int(np.argmax(p) == y),
            'brier': float((p@p-2*p[y]+1)/len(p))})
        probabilities.append(p)
    return rows, probabilities


def cell(folder, train, test, year, case):
    """訓練が必要な案だけ学習し、全予測と教師IDを新規セルへ保存する。

    Args:
        folder: 新規研究フォルダー。
        train: 当年より前の教師。
        test: 固定した当年確認集合。
        year: 評価年。
        case: 基準/混合/順位学習案の名前。
    Returns:
        保存済みモデル辞書と評価行。
    """
    old.prior.log('rank_cell', year=year, case=case, train=len(train))
    fitted = model.fit(train, case) if case in model.RANK_WEIGHTS else model.wrap(load_reference(year), case)
    path = folder/f'{year}_{case}.joblib'
    joblib.dump(fitted, path, compress=3)
    restored = joblib.load(path)
    rows, distributions = measure(test, restored, case)
    for index in (0, len(test)//2, len(test)-1):
        p = model.predict(fitted, model.core.clean(test[index]))
        old.require(np.array_equal(p, distributions[index]), 'rank_reload_mismatch')
        old.require(np.array_equal(p, model.predict(restored, {**test[index], 'winner': -1, 'payout_yen': 999999})), 'rank_result_dependency')
    joblib.dump(distributions, folder/f'{year}_{case}_predictions.joblib', compress=3)
    old.prior.save(folder/f'{year}_{case}.json', {'case': case, 'year': year,
        'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test],
        'trained_through': fitted['base_model']['trained_through'], 'model_sha256': old.prior.sha(path),
        'summary': old.prior.summary(rows), 'rows': rows, 'reused_H2': case in ('H2', 'G50')})
    old.prior.log('rank_evaluated', year=year, case=case, **old.prior.summary(rows))
    gc.collect()
    return fitted, rows


def choose(development):
    """2023だけの損失制約下で的中数最大・同数なら小損失の案を選ぶ。"""
    scores = {name: old.prior.summary(rows) for name, rows in development.items()}
    bound = scores['H2']['logloss']+.005
    eligible = [c for c in model.ORDER if scores[c]['logloss'] <= bound]
    hits = {c: sum(row['hit'] for row in development[c]) for c in eligible}
    maximum = max(hits.values())
    winners = [c for c in eligible if hits[c] == maximum]
    minimum = min(scores[c]['logloss'] for c in winners)
    selected = next(c for c in model.ORDER if c in winners and scores[c]['logloss'] <= minimum+1e-8)
    return {'chosen': selected, 'development': scores, 'eligible': eligible, 'max_logloss': bound,
            'criterion': '2023_top1_hits_under_H2_loss_plus_0.005_then_loss_then_simple', 'confirmation_used': False}


def run(folder):
    """固定開発選抜を別3年へ確認し、H2を置き換えられるか判定する。

    Notes:
        確認に失敗しても次点への選び直しをしない。失敗証跡と既存H2を保持する。
    """
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        initial = sources()
        for data_folder in (BASE, LATER):
            manifest = read(data_folder/'dataset-manifest.json')
            old.require(old.prior.sha(data_folder/'dataset.joblib') == manifest['sha256'], 'rank_dataset_sha')
        old.prior.save(folder/'protocol.json', {'protocol': model.PROTOCOL, 'created_at': datetime.now(timezone.utc).isoformat(),
            'source_sha256': initial, 'cases': list(model.ORDER), 'selection_year': 2023, 'confirmation_years': [2024, 2025, 2026],
            'max_new_fits': 6, 'unknown_test': False, 'dataset_sha256': old.prior.sha(BASE/'dataset.joblib'),
            'later_dataset_sha256': old.prior.sha(LATER/'dataset.joblib')})
        records = joblib.load(BASE/'dataset.joblib')['records']
        later = joblib.load(LATER/'dataset.joblib')['records']
        train = [r for r in records if r['race_date'] < '2023-01-01']
        test = [r for r in records if r['race_date'].startswith('2023')]
        stage = 'development'
        development = {case: cell(folder, train, test, 2023, case)[1] for case in model.ORDER}
        selection = choose(development)
        chosen = selection['chosen']
        old.prior.save(folder/'selection.json', selection)
        old.prior.log('rank_selection_frozen', chosen=chosen)
        stage = 'confirmation'
        evaluations, candidate_all, base_all, market_all = {}, [], [], []
        for year in (2024, 2025):
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = [r for r in records if r['race_date'].startswith(str(year))]
            _, baseline = cell(folder, train, test, year, 'H2')
            _, selected = cell(folder, train, test, year, chosen) if chosen != 'H2' else (None, baseline)
            market, _ = measure(test, None, 'M0')
            evaluations[str(year)] = {'selected': old.prior.grouped(selected), 'H2': old.prior.grouped(baseline), 'market': old.prior.grouped(market)}
            candidate_all.extend(selected)
            base_all.extend(baseline)
            market_all.extend(market)
        stage = 'final_fit'
        final = model.fit(records, chosen) if chosen in model.RANK_WEIGHTS else model.wrap(load_reference(2026), chosen)
        joblib.dump(final, folder/'final_model.joblib', compress=3)
        restored = joblib.load(folder/'final_model.joblib')
        old.require(np.array_equal(model.predict(final, model.core.clean(later[0])), model.predict(restored, model.core.clean(later[0]))), 'rank_final_reload')
        baseline, _ = measure(later, model.wrap(load_reference(2026), 'H2'), 'H2')
        selected, distributions = measure(later, restored, chosen)
        market, _ = measure(later, None, 'M0')
        joblib.dump(distributions, folder/'2026_selected_predictions.joblib', compress=3)
        old.prior.save(folder/'2026_selected.json', {'rows': selected, 'test_ids': [r['race_id'] for r in later]})
        evaluations['2026'] = {'selected': old.prior.grouped(selected), 'H2': old.prior.grouped(baseline), 'market': old.prior.grouped(market)}
        candidate_all.extend(selected)
        base_all.extend(baseline)
        market_all.extend(market)
        candidate, reference = old.prior.summary(candidate_all), old.prior.summary(base_all)
        ci = old.prior.comparison_ci(candidate_all, base_all)
        checks = {'more_total_hits_than_H2': sum(r['hit'] for r in candidate_all) > sum(r['hit'] for r in base_all),
            'pooled_logloss_within_H2_plus_0.002': candidate['logloss'] <= reference['logloss']+.002,
            'market_logloss_improves_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in evaluations.values()),
            'hit_rate_drop_within_half_pp_each_year': all(v['selected']['all']['hit_rate'] >= v['H2']['all']['hit_rate']-.005 for v in evaluations.values())}
        old.prior.save(folder/'assessment.json', {'selected': chosen, 'confirmation': evaluations,
            'pooled_selected': candidate, 'pooled_H2': reference, 'vs_H2_ci': ci,
            'vs_market_ci': old.prior.comparison_ci(candidate_all, market_all), 'replacement_checks': checks,
            'replace_H2_as_research_candidate': all(checks.values()), 'top1_superiority_evidence': ci['hit_rate_difference_ci95'][0] > 0,
            'production_adoption': False, 'unknown_test': False})
        old.require(sources() == initial, 'rank_source_changed')
        old.prior.save(folder/'model-manifest.json', {'protocol': model.PROTOCOL, 'selected': chosen,
            'model_sha256': old.prior.sha(folder/'final_model.joblib'), 'train_ids': [r['race_id'] for r in records],
            'trained_through': final['base_model']['trained_through'], 'source_sha256': initial,
            'assessment_sha256': old.prior.sha(folder/'assessment.json')})
        old.prior.save(folder/'verification.json', {'status': 'passed', 'reload_equal': True, 'result_ignored': True,
            'source_unchanged': True, 'selected_only_on_development': True})
        old.prior.log('rank_complete', chosen=chosen, checks=checks, pooled=candidate, H2=reference)
    except Exception as error:
        old.prior.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
