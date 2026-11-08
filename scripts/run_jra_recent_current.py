"""概要: 保存済み年別情報からS1の前走特徴を作り、4期間で固定比較する。
作成日: 2026-10-27
入力: spec430、D0/S0保存予測、年別保存カード、公式精算、保存事前原本。
出力: 新規runの特徴・来歴・4モデル・全確率・比較・互換検査・SHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_recent_current.py
注意事項: 過去追加取得・SQL・HTTP・購入・既定変更なし。既使用過去の研究。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter
from datetime import date
import gc
import gzip
import json
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_current_attributes as reuse
from jra_srb import jra_research_recent_current as model
from jra_srb.jra_research_contracts import ResearchError

ROOT, REFERENCE = reuse.ROOT, reuse.REFERENCE
read, save, sha, require, log = reuse.read, reuse.save, reuse.sha, reuse.require, reuse.log
S0 = ROOT/'artifacts/jra_research/current_attributes_S0_20261025'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/430-S1直近走特徴の固定研究.md'


def sources():
    """今回の仕様・実装と再利用コードを学習前に固定する。"""
    return {**reuse.sources(), **{str(p.relative_to(ROOT)): sha(p) for p in
        (SPEC, Path(__file__), Path(model.__file__), ROOT/'scripts/verify_jra_recent_current.py')}}


def prior_event(card, runner):
    """保存結果の前走用項目だけを抽出し、不完全な順位は無効として記録する。"""
    ranks = card['result']['ranks_by_horse']
    statuses = card['result']['runner_statuses']
    number = str(int(runner['horse_no']))
    n = len(statuses)
    complete = (2 <= n <= 18 and sorted(ranks.values()) == list(range(1, n+1))
                and all(row.get('abnormal_code') == '0' for row in statuses.values()))
    return {'race_id': card['race_id'], 'race_date': card['race_date'],
            'surface': {'turf': 0, 'dirt': 1}.get(card['race']['surface']),
            'distance': card['race']['distance'], 'rank': ranks.get(number), 'field_size': n,
            'valid': bool(complete)}


def prepare(folder, records, later, card_hashes):
    """年別カードを日付順に一度読み、同日結果反映前の特徴と参照元を保存する。

    Args:
        folder: 新規成果物フォルダー。
        records: 元D0の2020〜25年教師。
        later: 元D0の2026年確認集合。
        card_hashes: 元D0に記録された年別カードSHA。
    Returns:
        履歴15列を除いたS1教師・確認集合。
    Notes:
        既存カードの結果は次日以降の履歴作成にだけ使う。SQL/HTTPなし。
    """
    wanted = {r['race_id']: r for r in records+later}
    latest, prepared, coverage = {}, {}, {}
    provenance_path = folder/'feature-provenance.jsonl.gz'
    with gzip.open(provenance_path, 'xt', encoding='utf-8') as provenance:
        for year in range(2020, 2027):
            path = next(ROOT/p for p in card_hashes if f'\\{year}\\' in p or f'/{year}/' in p)
            require(sha(path) == card_hashes[str(path.relative_to(ROOT))], 'S1_card_sha')
            counts, day_cards, current_day = Counter(), [], None
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                for line in stream:
                    card = json.loads(line)
                    day = card['race_date']
                    require(day.startswith(str(year)) and (current_day is None or day >= current_day), 'S1_card_date_order')
                    if current_day is not None and day != current_day:
                        prepare_day(day_cards, latest, wanted, prepared, counts, provenance)
                        day_cards = []
                    current_day = day
                    day_cards.append(card)
                if day_cards:
                    prepare_day(day_cards, latest, wanted, prepared, counts, provenance)
            coverage[str(year)] = dict(counts)
            log('S1_features_year', year=year, counts=dict(counts))
    require(set(prepared) == set(wanted), 'S1_features_incomplete')
    result = {'records': [prepared[r['race_id']] for r in records],
              'later': [prepared[r['race_id']] for r in later], 'protocol': model.PROTOCOL}
    joblib.dump(result, folder/'dataset.joblib', compress=3)
    save(folder/'feature-coverage.json', coverage)
    save(folder/'dataset-manifest.json', {'sha256': sha(folder/'dataset.joblib'),
        'provenance_sha256': sha(provenance_path), 'coverage': coverage,
        'card_sha256': card_hashes, 'history_publication_time_verified': False})
    return result['records'], result['later']


def prepare_day(cards, latest, wanted, prepared, counts, provenance):
    """当日全対象の特徴確定後に、前走用状態へ当日結果を反映する。"""
    for card in cards:
        key = card['race_id']
        counts['source_races'] += 1
        if key not in wanted:
            continue
        require(key not in prepared, 'S1_duplicate_race')
        r = wanted[key]
        runners = {f"{int(row['horse_no']):02d}": row for row in card['inputs']['runners']}
        require(len(runners) == len(card['inputs']['runners']) and set(r['horses']).issubset(runners), 'S1_card_roster')
        recent, references = [], []
        for horse in r['horses']:
            row = runners[horse]
            identity = str(row.get('horse_id') or '')
            require(identity.isdigit() and len(identity) == 10 and int(identity) > 0, 'S1_horse_id')
            previous = latest.get(identity)
            h = row['history_features']
            has = float(h['horse_has_history'])
            interval = float(h['days_since_last_scaled'])*365
            chosen = previous
            reason_override = None
            if previous is not None:
                days = (date.fromisoformat(r['race_date'])-date.fromisoformat(previous['race_date'])).days
                require(days > 0, 'S1_history_same_day')
                if has != 1 or abs(interval-min(days, 365)) > 1e-4:
                    chosen, reason_override = None, 'stored_interval_mismatch'
            values, reason = model.recent_vector(r['race_date'], r['surface'], r['distance'], chosen)
            reason = reason_override or reason
            counts['runners'] += 1
            counts[reason] += 1
            recent.append(values)
            references.append({'horse_no': horse, 'horse_id': identity, 'previous': previous,
                               'stored_has_history': has, 'stored_interval_days': interval, 'reason': reason})
        prepared[key] = model.base.clean(r)|{'recent': np.asarray(recent, dtype=np.float32), 'winner': r['winner']}
        if 'payout_yen' in r:
            prepared[key]['payout_yen'] = r['payout_yen']
        provenance.write(json.dumps({'race_id': key, 'race_date': r['race_date'], 'references': references}, ensure_ascii=False)+'\n')
        counts['target_races'] += 1
    seen = set()
    for card in cards:
        for row in card['inputs']['runners']:
            identity = str(row.get('horse_id') or '')
            if not identity.isdigit() or len(identity) != 10 or int(identity) == 0:
                continue
            require(identity not in seen, 'S1_same_horse_multiple_daily_events')
            seen.add(identity)
            latest[identity] = prior_event(card, row)


def run(folder):
    """S1一構成を4回学習し、固定比較・原本推論・採否を保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        require(all(sha(ROOT/p) == value for p, value in initial.items()), 'S1_sources')
        s0_manifest = read(S0/'manifest.json')
        require(read(S0/'independent-verification.json')['status'] == 'passed'
                and all(sha(S0/p) == value for p, value in s0_manifest['files_sha256'].items()), 'S1_S0_reference')
        cards = read(REFERENCE/'dataset-manifest.json')['card_sha256']
        frozen = {**cards, **{str(p.relative_to(ROOT)): sha(p) for p in
                    (S0/'manifest.json', S0/'independent-verification.json', reuse.OUTCOMES, reuse.CAPTURE/'inputs.jsonl.gz')}}
        save(folder/'protocol.json', {'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'max_new_fits': 4, 'cases': ['S1'], 'unknown_test': False, 'purchase_allowed': False})
        records, later, d0 = reuse.reuse.load_inputs(folder)
        stage = 'features'
        records, later = prepare(folder, records, later, cards)
        outcomes = read(reuse.OUTCOMES)
        annual, pooled, models = {}, {key: [] for key in ('S1', 'S0', 'D0', 'market')}, {}
        for year in (2023, 2024, 2025, 2026):
            stage = f'fit_{year}'
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
            log('S1_fit_start', year=year, train=len(train), test=len(test))
            fitted = model.fit(train)
            path = folder/f'{year}_S1.joblib'
            joblib.dump(fitted, path, compress=3)
            restored = joblib.load(path)
            p = [model.predict(restored, r) for r in test]
            require(np.array_equal(model.predict(fitted, test[0]), p[0]), 'S1_reload')
            s0 = joblib.load(S0/f'{year}_S0_predictions.joblib')
            require(read(S0/f'{year}_S0.json')['test_ids'] == [r['race_id'] for r in test], 'S1_S0_roster')
            rows = {label: reuse.rows_for(test, probabilities, label, outcomes) for label, probabilities in
                    [('S1', p), ('S0', s0), ('D0', [d0[r['race_id']] for r in test]), ('market', [r['market'] for r in test])]}
            annual[str(year)] = {k: reuse.summary(v) for k, v in rows.items()}
            joblib.dump(p, folder/f'{year}_S1_predictions.joblib', compress=3)
            models[path.name] = sha(path)
            save(folder/f'{year}_S1.json', {'train_ids': [r['race_id'] for r in train],
                 'test_ids': [r['race_id'] for r in test], 'model_sha256': models[path.name], 'rows': rows,
                 'summary': annual[str(year)]})
            if year == 2023:
                a, b = annual['2023']['S1'], annual['2023']['S0']
                selected = a['logloss'] < b['logloss'] and a['hit_rate'] >= b['hit_rate']
                save(folder/'selection.json', {'S1_selected': selected, 'confirmation_used': False, 'summary': annual['2023']})
            else:
                for key in pooled:
                    pooled[key].extend(rows[key])
            log('S1_fit_complete', year=year, summary=annual[str(year)])
            del train, restored, p, s0
            gc.collect()
        stage = 'assessment'
        totals = {k: reuse.summary(v) for k, v in pooled.items()}
        intervals = {k: reuse.reuse.helper.comparison_ci(pooled['S1'], pooled[k]) for k in ('S0', 'D0', 'market')}
        checks = {'development_selected': selected, 'S0_loss_ci_positive': intervals['S0']['loss_improvement_ci95'][0] > 0,
                  'hits_at_least_S0': totals['S1']['hit_rate'] >= totals['S0']['hit_rate'],
                  'market_loss_better_each_year': all(annual[str(y)]['S1']['logloss'] < annual[str(y)]['market']['logloss'] for y in (2024, 2025, 2026))}
        d0_checks = {'D0_loss_ci_positive': intervals['D0']['loss_improvement_ci95'][0] > 0,
                     'hits_at_least_D0': totals['S1']['hit_rate'] >= totals['D0']['hit_rate']}
        save(folder/'assessment.json', {'annual': annual, 'pooled': totals, 'intervals': intervals,
            'checks': checks, 'D0_checks': d0_checks, 'promising_S0_improvement': all(checks.values()),
            'promising_D0_replacement': all(checks.values()) and all(d0_checks.values()),
            'grouped': {k: reuse.reuse.helper.grouped(v) for k, v in pooled.items()},
            'unknown_test': False, 'purchase_allowed': False, 'default_changed': False})
        stage = 'capture_replay'
        accepted, rejected, reasons = [], [], Counter()
        with gzip.open(reuse.CAPTURE/'inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                obs = json.loads(line)
                try:
                    r, provenance = model.from_capture(obs)
                    pp = model.predict(fitted, r)
                    reasons.update(provenance['reasons'])
                    accepted.append({'observation_index': index, 'race_id': r['race_id'], 'timing': obs['timing'],
                        'horses': r['horses'], 'recent': r['recent'].tolist(), 'provenance': provenance,
                        'probabilities': pp.tolist()})
                except (ResearchError, ValueError, KeyError) as error:
                    rejected.append({'observation_index': index, 'race_id': obs['race_id'],
                                     'reason': getattr(error, 'reason', type(error).__name__)})
        save(folder/'capture-replay.json', {'accepted': accepted, 'rejected': rejected,
             'accepted_races': len({r['race_id'] for r in accepted}), 'recent_coverage': dict(reasons),
             'performance_test': False, 'live_prediction_saved': False})
        require(sources() == initial and all(sha(ROOT/p) == v for p, v in initial.items())
                and all(sha(ROOT/p) == v for p, v in frozen.items()), 'S1_sources_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
             'model_sha256': models, 'new_fits': 4, 'D0_refits': 0, 'S0_refits': 0,
             'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        log('S1_complete', pooled=totals, checks=checks, D0_checks=d0_checks, accepted=len(accepted), rejected=len(rejected))
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/jra_research/recent_current_S1_20261027')
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
