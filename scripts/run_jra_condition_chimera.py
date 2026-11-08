"""概要: 条件別キメラ3案の固定比較・最終学習と、保存モデルの研究推論を行う。
作成日: 2026-10-24
入力: trainは固定SQL履歴/v2市場、scoreは保存モデルと発走前特徴JSON。
出力: 指定新規フォルダーのモデル・時系列評価・件数・来歴・保存後検証。
実行例: uv run --frozen --extra ml python scripts/run_jra_condition_chimera.py train --output artifacts/jra_research/condition_chimera_20261024
注意事項: SQLはSELECTのみ。既存データ上書き・実購入・既定変更なし。数値スレッド1。
"""

from __future__ import annotations

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from jra_srb import jra_research_condition_chimera as model
from jra_srb import jra_research_chimera_thirty_features as features
from jra_srb.jra_research_history import HistoryConfig
from jra_srb.jra_research_r1_live import LiveAnnualReader, require
from jra_srb.jra_research_resources import check_memory


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/350-条件別キメラ検証モデル実装契約.md'
HELPER = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/diagnostics/backtest_j23_early_autumn_20261023.py'


def save(path, value):
    """新規JSONだけをUTF-8/LFで保存し、NaNと意図しない上書きを拒否する。"""
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def sha(path):
    """公開成果物/コードのSHA256を返す。"""
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def log(stage, **values):
    """秘密値を含まない処理段階と件数を即時出力する。"""
    print(json.dumps({'stage': stage, **values}, ensure_ascii=False), flush=True)


def parse_updates(raw):
    """既存SDK解析で正常平地8頭以上を日別にまとめる。

    Returns:
        日別の(競走,時計秒,馬場コード)一覧と除外理由件数。
    Notes:
        原文を変更せず、既存の時計・馬場・ラップ解釈を再利用する。
    """
    daily, excluded = defaultdict(list), Counter()
    for key, source in sorted(raw.items()):
        race, reason = features.old.native.parse_race(key, source)
        if reason:
            excluded[reason] += 1
            continue
        ra = source['RA'][2]
        seconds = {r['horse_no']: features.old.clock_seconds(source['SE'][r['horse_no']][2][338:342])
                   for r in race['runners']}
        going = features.old.native.number(ra[888:889] if race['surface'] == 0 else ra[889:890])
        require(going in (1, 2, 3, 4), 'condition_invalid_going')
        laps = [features.old.native.number(ra[890+i*3:893+i*3])/10 for i in range(25)]
        # 正のラップだけから末尾3区間を選ぶ既存経路と一致させる。
        race['closing_total'] = sum([v for v in laps if v > 0][-3:]) if race['pace'] is not None else None
        daily[race['day']].append((race, seconds, going))
    return daily, dict(excluded)


def prepare(folder):
    """新仮説用15特徴を一度だけ構築し、原文を保存せず派生特徴と状態を保存する。"""
    spec = importlib.util.spec_from_file_location('condition_market_helper', HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    prices, market_hashes = helper.markets(folder, end_year=2025)
    audit = json.loads((features.old.AUDIT/'audit.json').read_text('utf-8'))
    states, records, coverage, rejected = model.ConditionStates(), [], {}, []
    names = defaultdict(set)
    latest = {}
    config = HistoryConfig.load(ROOT/'configs/research/history_sql_v1.json')
    with LiveAnnualReader(config) as reader:
        save(folder/'sql-preflight.json', reader.preflight())
        for year in range(2003, 2026):
            raw, report = reader.year_before(year, '2026-01-01')
            require(report['input_digest'] == audit['annual'][str(year)]['source_audit']['input_digest'],
                    'condition_annual_digest_changed')
            daily, excluded = parse_updates(raw)
            for source in raw.values():
                for _, _, se in source['SE'].values():
                    name = se[40:76].decode('cp932').strip().replace('\u3000', '')
                    born = year-features.old.native.number(se[82:84])
                    names[(name, born)].add(se[30:40].decode('ascii'))
            del raw
            accepted = 0
            for day, updates in sorted(daily.items()):
                for race, _, going in updates:
                    key = race['key']
                    if key not in prices:
                        continue
                    market = prices[key]
                    horses = [r['horse_no'] for r in race['runners']]
                    if horses != market['horses'] or any(r['rank'] != market['ranks'][r['horse_no']] for r in race['runners']):
                        rejected.append({'race_id': key, 'reason': 'roster_or_ranks_mismatch'})
                        continue
                    x = states.condition_public(race)
                    records.append({'race_id': key, 'race_date': day, 'course': race['course'],
                                    'surface': race['surface'], 'distance': race['distance'],
                                    'condition': race['condition'], 'going': going, 'horses': horses,
                                    'x': x, 'winner': list(map(tuple, model.pairs(len(horses)))).index(
                                        tuple(i for i, r in enumerate(race['runners']) if r['rank'] <= 2)),
                                    'market': market['market'], 'payout_yen': market['payout_yen']})
                    accepted += 1
                states.update_day(updates)
                for race, _, _ in updates:
                    for runner in race['runners']:
                        latest[runner['horse_id']] = day
            coverage[str(year)] = {**report, 'excluded': excluded, 'target_races': accepted,
                                   'normal_history': sum(map(len, daily.values()))}
            save(folder/f'coverage-{year}.json', coverage[str(year)])
            log('features', year=year, records=len(records), memory_bytes=check_memory(model.MEMORY_LIMIT))
            del daily
            gc.collect()
    records.sort(key=lambda r: (r['race_date'], r['race_id']))
    require(bool(records) and len({r['race_id'] for r in records}) == len(records), 'condition_feature_identity')
    save(folder/'feature-exclusions.json', rejected)
    save(folder/'coverage.json', coverage)
    dataset = {'protocol': model.PROTOCOL, 'records': records, 'market_hashes': market_hashes,
               'source_sha256': source_hashes(), 'features': list(model.FEATURES)}
    joblib.dump(dataset, folder/'dataset.joblib', compress=3)
    joblib.dump({'states': states, 'names': dict(names), 'latest': latest, 'history_before': '2026-01-01',
                 'coverage': coverage, 'protocol': model.PROTOCOL}, folder/'history_state.joblib', compress=3)
    save(folder/'dataset-manifest.json', {'sha256': sha(folder/'dataset.joblib'), 'records': len(records),
        'history_state_sha256': sha(folder/'history_state.joblib'), 'source_sha256': source_hashes()})
    del states, names, latest, prices
    gc.collect()
    return records


def source_hashes():
    """仕様と今回再利用した特徴実装の来歴を固定する。"""
    paths = [SPEC, Path(__file__), Path(model.__file__), Path(features.old.__file__),
             Path(features.previous.__file__), Path(features.old.native.__file__), HELPER]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def measure(records, fitted, label):
    """同一競走の全分布から損失・的中・Brierだけを測り、購入政策を作らない。"""
    rows = []
    for record in records:
        p = np.asarray(record['market']) if fitted is None else model.predict(fitted, model.clean_record(record))
        target = record['winner']
        rows.append({'race_id': record['race_id'], 'race_date': record['race_date'], 'label': label,
                     'course': record['course'], 'surface': record['surface'],
                     'distance_band': model.distance_band(record['distance']), 'season': model.season(record['race_date']),
                     'loss': float(-np.log(p[target])), 'hit': int(np.argmax(p) == target),
                     'brier': float((p@p-2*p[target]+1)/len(p))})
    return rows


def summary(rows):
    """集合の件数と平均予測性能を返し、空集合は明示する。"""
    return {'races': len(rows), 'days': len({r['race_date'] for r in rows}),
            'logloss': float(np.mean([r['loss'] for r in rows])) if rows else None,
            'hit_rate': float(np.mean([r['hit'] for r in rows])) if rows else None,
            'brier': float(np.mean([r['brier'] for r in rows])) if rows else None}


def comparison_ci(candidate, reference):
    """同じ開催日を対で再抽出し、対照損失−候補損失と的中差の95%区間を返す。"""
    require([r['race_id'] for r in candidate] == [r['race_id'] for r in reference], 'condition_comparison_cohort')
    daily = defaultdict(lambda: np.zeros(3))
    for a, b in zip(candidate, reference, strict=True):
        daily[a['race_date']] += [b['loss']-a['loss'], a['hit']-b['hit'], 1]
    data = np.asarray([daily[d] for d in sorted(daily)])
    require(bool(len(data)), 'condition_empty_evaluation')
    rng = np.random.default_rng(350)
    samples = np.asarray([data[rng.integers(0, len(data), len(data))].sum(axis=0) for _ in range(2000)])
    return {'days': len(data), 'draws': 2000, 'loss_improvement_ci95': np.quantile(samples[:, 0]/samples[:, 2], [.025, .975]).tolist(),
            'hit_rate_difference_ci95': np.quantile(samples[:, 1]/samples[:, 2], [.025, .975]).tolist()}


def grouped(rows):
    """年・場・芝ダート・距離・季節別の全セルを欠落なく集計する。"""
    result = {'all': summary(rows)}
    for axis in ('course', 'surface', 'distance_band', 'season'):
        result[axis] = {str(v): summary([r for r in rows if r[axis] == v]) for v in sorted({r[axis] for r in rows})}
    return result


def train(folder, dataset=None):
    """事前固定の3案と4除去診断を評価し、選抜した1案を2025年末までで最終学習する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        initial_sources = source_hashes()
        save(folder/'protocol.json', {'protocol': model.PROTOCOL, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_sha256': initial_sources, 'train': ['2020-01-01', '2023-12-31'],
            'development': '2024', 'confirmation': '2025', 'cases': ['C0', 'C1', 'C2'],
            'fit_limit': 8, 'unknown_test': False, 'market_model_input': False,
            'minimum_context_races': 100, 'distance_edges_m': [1400, 1800, 2200, 2600], 'production_adoption': False})
        stage = 'features'
        if dataset:
            manifest = json.loads((dataset.parent/'dataset-manifest.json').read_text('utf-8'))
            require(sha(dataset) == manifest['sha256'], 'condition_dataset_sha')
            loaded = joblib.load(dataset)
            require(loaded['protocol'] == model.PROTOCOL and loaded['features'] == list(model.FEATURES)
                    and loaded['source_sha256'] == initial_sources, 'condition_dataset_contract')
            records = loaded['records']
            save(folder/'reused-dataset.json', {'path': str(dataset.resolve()), 'sha256': sha(dataset)})
        else:
            records = prepare(folder)
        train_rows = [r for r in records if '2020-01-01' <= r['race_date'] < '2024-01-01']
        dev = [r for r in records if r['race_date'].startswith('2024')]
        test = [r for r in records if r['race_date'].startswith('2025')]
        require(len(train_rows) >= 1000 and len(dev) >= 500 and len(test) >= 500, 'condition_incomplete_periods')
        cells = Counter((r['race_date'][:4], r['course'], r['surface'], model.distance_band(r['distance']), model.season(r['race_date'])) for r in records)
        save(folder/'condition-counts.json', [{'year': k[0], 'course': k[1], 'surface': k[2], 'distance_band': k[3],
                                             'season': k[4], 'races': n} for k, n in sorted(cells.items())])
        models, development_rows, evaluations, ablations = {}, {}, {}, {}
        for case in ('C0', 'C1', 'C2'):
            stage = 'fit_'+case
            log(stage, train_races=len(train_rows))
            fitted = model.fit(train_rows, case)
            joblib.dump(fitted, folder/f'{case}.joblib', compress=3)
            models[case] = fitted
            development_rows[case] = measure(dev, fitted, case)
            log('development', case=case, **summary(development_rows[case]), optimizer=fitted['optimizer'])
            gc.collect()
        minimum = min(summary(rows)['logloss'] for rows in development_rows.values())
        chosen = next(c for c in ('C0', 'C1', 'C2') if summary(development_rows[c])['logloss'] <= minimum+1e-8)
        save(folder/'selection.json', {'chosen': chosen, 'criterion': '2024_logloss_only_tie_simplest_1e-8',
             'development': {c: summary(r) for c, r in development_rows.items()}, 'test_consulted': False})
        for block in model.BLOCKS:
            stage = 'ablation_'+block
            log(stage, case=chosen)
            fitted = model.fit(train_rows, chosen, omitted=block)
            joblib.dump(fitted, folder/f'without_{block}.joblib', compress=3)
            ablations[block] = {'development': summary(measure(dev, fitted, 'without_'+block)),
                                'confirmation': grouped(measure(test, fitted, 'without_'+block))}
            del fitted
            gc.collect()
        stage = 'confirmation'
        market_rows = measure(test, None, 'M0')
        for case, fitted in models.items():
            evaluations[case] = measure(test, fitted, case)
        candidate, common = evaluations[chosen], evaluations['C0']
        interval = comparison_ci(candidate, market_rows)
        kyoto_long = [r for r in candidate if r['course'] == 8 and r['surface'] == 0 and r['distance_band'] == 4]
        checks = {'market_logloss_improved': summary(candidate)['logloss'] < summary(market_rows)['logloss'],
                  'common_logloss_improved': chosen != 'C0' and summary(candidate)['logloss'] < summary(common)['logloss'],
                  'market_loss_ci_positive': interval['loss_improvement_ci95'][0] > 0,
                  'market_hit_rate_not_worse': summary(candidate)['hit_rate'] >= summary(market_rows)['hit_rate'],
                  'kyoto_long_at_least_30': len(kyoto_long) >= 30}
        save(folder/'evaluation-ledger.json', {'development': development_rows, 'confirmation': evaluations, 'market': market_rows})
        save(folder/'assessment.json', {'chosen': chosen, 'confirmation': {c: grouped(r) for c, r in evaluations.items()},
            'market': grouped(market_rows), 'development_market': summary(measure(dev, None, 'M0')),
            'ablations': ablations, 'vs_market_ci': interval, 'vs_common_ci': comparison_ci(candidate, common),
            'kyoto_turf_long': summary(kyoto_long), 'research_candidate_checks': checks,
            'research_candidate_passed': all(checks.values()), 'production_adoption': False,
            'unknown_validation': False, 'purchase_policy_evaluated': False,
            'historical_publication_verified': False})
        stage = 'final_fit'
        log(stage, case=chosen, train_races=len(records))
        final = model.fit(records, chosen)
        joblib.dump(final, folder/'final_model.joblib', compress=3)
        restored = joblib.load(folder/'final_model.joblib')
        # 読戻し/結果遮断の検証用に、訓練用の公開特徴を未来日へ移した機械的推論を使う。
        # このサンプルは事前予想でも未来レースの性能評価でもない。
        sample = model.clean_record(test[-1])
        sample['race_date'] = '2026-10-25'
        sample['race_id'] = 'synthetic_reload_check'
        p = model.predict(final, sample)
        require(np.array_equal(p, model.predict(restored, sample)), 'condition_reload_mismatch')
        require(np.array_equal(p, model.predict(restored, {**sample, 'winner': 999, 'market': None, 'payout_yen': -1})),
                'condition_result_or_market_dependency')
        save(folder/'sample_input.json', {**sample, 'x': sample['x'].tolist()})
        save(folder/'sample_forecast.json', {**model.forecast(restored, sample), 'synthetic_check_only': True})
        require(source_hashes() == initial_sources, 'condition_source_changed')
        save(folder/'model-manifest.json', {'protocol': model.PROTOCOL, 'model_sha256': sha(folder/'final_model.joblib'),
            'selected_case': chosen, 'train_races': final['train_races'], 'trained_from': final['trained_from'],
            'trained_through': final['trained_through'], 'training_race_ids': [r['race_id'] for r in records],
            'source_sha256': initial_sources, 'selection_sha256': sha(folder/'selection.json'),
            'assessment_sha256': sha(folder/'assessment.json'), 'research_only': True})
        save(folder/'verification.json', {'status': 'passed', 'fits': 8, 'reload_equal': True,
            'result_and_market_ignored': True, 'probability_sum': float(p.sum()), 'source_unchanged': True,
            'model_created': True, 'research_candidate_passed': all(checks.values()), 'production_adoption': False})
        log('complete', selected=chosen, model=str(folder/'final_model.joblib'), research_candidate_passed=all(checks.values()))
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


def score(model_path, input_path, output):
    """manifest一致の自作モデルと前日特徴JSONから、新規ファイルへ参考推論を保存する。"""
    manifest = json.loads((model_path.parent/'model-manifest.json').read_text('utf-8'))
    require(sha(model_path) == manifest['model_sha256'], 'condition_model_sha_mismatch')
    fitted = joblib.load(model_path)
    record = json.loads(input_path.read_text('utf-8'))
    save(output, model.forecast(fitted, record))
    log('scored', race_id=record['race_id'], output=str(output))


def main():
    """訓練と保存モデル推論を別サブコマンドとして受け付ける。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    training = sub.add_parser('train')
    training.add_argument('--output', type=Path, required=True)
    training.add_argument('--dataset', type=Path)
    scoring = sub.add_parser('score')
    scoring.add_argument('--model', type=Path, required=True)
    scoring.add_argument('--input', type=Path, required=True)
    scoring.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        if args.command == 'train':
            train(args.output, args.dataset)
        else:
            score(args.model, args.input, args.output)


if __name__ == '__main__':
    main()
