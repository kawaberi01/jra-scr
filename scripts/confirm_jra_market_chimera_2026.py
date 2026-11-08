"""概要: 固定した市場基準キメラを追加の2026年で確認し、年代を跨ぐ見込みを調べる。
作成日: 2026-10-24
入力: spec355の最終モデル、2025末履歴状態、2026年9月末までの固定SQLと市場。
出力: 新規確認dirの派生特徴・全予測・比較・確認判定。
実行例: uv run --frozen --extra ml python scripts/confirm_jra_market_chimera_2026.py prepare --output artifacts/jra_research/market_condition_2026_inputs_20261024
注意事項: SQL SELECTのみ、原文保存なし、結果前の特徴生成を維持。既使用過去の追加確認。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
import gc
import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_market_chimera as runner


HISTORY = runner.ROOT/'artifacts/jra_research/condition_chimera_20261024'


def prepare(folder):
    """2025末checkpointを再利用し、2026年だけ前日特徴と同時点市場を結合する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        prior = runner.prior
        prior.save(folder/'protocol.json', {'cutoff': '2026-10-01', 'training_used': False,
            'purpose': 'fixed_spec355_candidate_later_period_confirmation', 'is_unseen_test': False,
            'script_sha256': prior.sha(Path(__file__))})
        manifest = prior.features.read_json(HISTORY/'dataset-manifest.json')
        prior.require(prior.sha(HISTORY/'history_state.joblib') == manifest['history_state_sha256'], 'market_later_history_sha')
        checkpoint = joblib.load(HISTORY/'history_state.joblib')
        states = checkpoint['states']
        del checkpoint
        stage = 'markets'
        spec = importlib.util.spec_from_file_location('market_later_helper', prior.HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        markets, _ = helper.markets(folder, end_year=2026)
        markets = {key: value for key, value in markets.items() if key.startswith('2026')}
        stage = 'history_2026'
        config = prior.HistoryConfig.load(runner.ROOT/'configs/research/history_sql_v1.json')
        with prior.LiveAnnualReader(config) as reader:
            prior.save(folder/'preflight.json', reader.preflight())
            raw, report = reader.year_before(2026, '2026-10-01')
        daily, excluded = prior.parse_updates(raw)
        del raw
        records = []
        for day, updates in sorted(daily.items()):
            for race, _, going in updates:
                key = race['key']
                if key not in markets:
                    continue
                market = markets[key]
                horses = [r['horse_no'] for r in race['runners']]
                prior.require(horses == market['horses'] and all(r['rank'] == market['ranks'][r['horse_no']] for r in race['runners']), 'market_later_roster')
                winner = next(i for i, pair in enumerate(runner.model.base.pairs(len(horses)))
                              if tuple(horses[j] for j in pair) == market['winner_horses'])
                records.append({'race_id': key, 'race_date': day, 'course': race['course'], 'surface': race['surface'],
                    'distance': race['distance'], 'condition': race['condition'], 'going': going, 'horses': horses,
                    'x': states.condition_public(race), 'winner': winner, 'market': market['market'], 'pl': market['pl']})
            states.update_day(updates)
        prior.require(len(records) >= 500 and max(r['race_date'] for r in records) < '2026-10-01', 'market_later_cohort')
        records.sort(key=lambda r: (r['race_date'], r['race_id']))
        joblib.dump({'records': records, 'protocol': runner.model.PROTOCOL}, folder/'dataset.joblib', compress=3)
        prior.save(folder/'dataset-manifest.json', {'sha256': prior.sha(folder/'dataset.joblib'), 'records': len(records),
            'history_checkpoint_sha256': manifest['history_state_sha256'], 'coverage': report, 'excluded': excluded,
            'first_date': records[0]['race_date'], 'last_date': records[-1]['race_date']})
        prior.log('later_inputs_ready', records=len(records), last_date=records[-1]['race_date'])
    except Exception as error:
        runner.prior.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


def evaluate(folder, inputs, training_run):
    """選抜済み構成を変えず、追加年と市場/純市場対照の差を確認する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        prior = runner.prior
        manifest = prior.features.read_json(training_run/'model-manifest.json')
        source = prior.features.read_json(inputs/'dataset-manifest.json')
        prior.require(prior.sha(training_run/'final_model.joblib') == manifest['model_sha256'], 'market_later_model_sha')
        prior.require(prior.sha(inputs/'dataset.joblib') == source['sha256'], 'market_later_input_sha')
        prior.require(prior.features.read_json(training_run/'independent-verification.json')['status'] == 'passed', 'market_later_unverified_model')
        prior.save(folder/'protocol.json', {'training_run': str(training_run), 'inputs': str(inputs),
            'selected_before_reading_later_results': manifest['selected_case'], 'model_sha256': manifest['model_sha256'],
            'input_sha256': source['sha256'], 'candidate_reselection': False, 'is_unseen_test': False,
            'script_sha256': prior.sha(Path(__file__))})
        records = joblib.load(inputs/'dataset.joblib')['records']
        train = joblib.load(training_run/'dataset.joblib')['records']
        fitted = joblib.load(training_run/'final_model.joblib')
        stage = 'fixed_candidate'
        candidate, predictions = runner.measure(records, fitted, fitted['case'])
        joblib.dump(predictions, folder/'selected_predictions.joblib', compress=3)
        market, _ = runner.measure(records, None, 'M0')
        rows = {'selected': candidate, 'market': market}
        for case in ('T0', 'P0'):
            stage = 'control_'+case
            control = runner.model.fit(train, case)
            joblib.dump(control, folder/f'{case}.joblib', compress=3)
            measured, predictions = runner.measure(records, control, case)
            joblib.dump(predictions, folder/f'{case}_predictions.joblib', compress=3)
            rows[case] = measured
            gc.collect()
        summaries = {name: prior.grouped(value) for name, value in rows.items()}
        interval = prior.comparison_ci(candidate, market)
        checks = {'market_loss_improves': summaries['selected']['all']['logloss'] < summaries['market']['all']['logloss'],
            'calibration_loss_improves': summaries['selected']['all']['logloss'] < summaries['T0']['all']['logloss'],
            'hit_rate_drop_at_most_half_pp': summaries['selected']['all']['hit_rate'] >= summaries['market']['all']['hit_rate']-.005}
        prior.save(folder/'ledger.json', rows)
        prior.save(folder/'assessment.json', {'case': fitted['case'], 'summaries': summaries, 'vs_market_ci': interval,
            'vs_calibration_ci': prior.comparison_ci(candidate, rows['T0']), 'vs_crossmarket_ci': prior.comparison_ci(candidate, rows['P0']),
            'later_period_checks': checks, 'later_period_supported': all(checks.values()), 'production_adoption': False,
            'unknown_test': False, 'candidate_reselected': False})
        prior.log('later_confirmation_complete', checks=checks, summaries={k:v['all'] for k,v in summaries.items()})
    except Exception as error:
        runner.prior.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--output', type=Path, required=True)
    e = sub.add_parser('evaluate')
    e.add_argument('--output', type=Path, required=True)
    e.add_argument('--inputs', type=Path, required=True)
    e.add_argument('--training-run', type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        if args.command == 'prepare':
            prepare(args.output)
        else:
            evaluate(args.output, args.inputs, args.training_run)
