"""概要: 保存T10の完全市場でS10/M10各4モデルを学習し固定購入も比較する。
作成日: 2026-11-07
入力: spec451、元dataset/年別保存市場、S0保存モデル、spec450完了判定。
出力: 新規runのT10 dataset、8モデル/全確率、精算/区間/原本互換とSHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_ten_minute.py
注意事項: 過去追加取得・SQL/HTTP・既定変更・実購入なし。既使用過去の研究。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import datetime, timedelta
import gc
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_purchase_operability as reuse
from jra_srb import jra_research_ten_minute as model
from jra_srb import jra_research_purchase_portfolio as policy
from jra_srb.jra_research_contracts import ResearchError

ROOT, read, save, sha, require = reuse.ROOT, reuse.read, reuse.save, reuse.sha, reuse.require
REF = reuse.prior.old.REFERENCE
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/451-T10同時点学習と市場変化モデル.md'
PREVIOUS = ROOT / 'artifacts/jra_research/purchase_operability_20261107_v2'


def sources():
    """仕様と実装・再利用学習/精算のソースSHAを事前固定する。"""
    return {str(p.relative_to(ROOT)): sha(p) for p in (SPEC, Path(__file__), Path(model.__file__),
        Path(model.base.__file__), Path(model.base.core.__file__), Path(policy.__file__),
        ROOT / 'scripts/verify_jra_ten_minute.py', ROOT / 'tests/test_jra_ten_minute.py')}


def numeric(quote, bet, horses):
    """保存市場の完全名簿と有限価格を確かめ、既存ペア順で配列化する。"""
    if bet == 'win':
        mapping = {f"{int(v['horse_no']):02d}": float(v['odds']) for v in quote['horses'] if v['status'] == 'numeric'}
        keys = horses
        size = len(quote['horses'])
    else:
        mapping = {tuple(sorted((f"{int(v['horse_no_1']):02d}", f"{int(v['horse_no_2']):02d}"))): float(v['odds'])
                   for v in quote['pairs'] if v['status'] == 'numeric'}
        keys = list(combinations(horses, 2))
        size = len(quote['pairs'])
    require(set(mapping) == set(keys) and size == len(mapping), 'T10_incomplete_market')
    odds = np.asarray([mapping[k] for k in keys])
    require(np.isfinite(odds).all() and min(odds) >= 1, 'T10_invalid_price')
    return odds


def dataset(folder):
    """T10原本を時刻・市場・正解照合し、結果を特徴から分離して保存する。"""
    manifest = read(REF / 'model-manifest.json')
    require(sha(REF / 'dataset.joblib') == manifest['dataset_sha256'], 'T10_reference_dataset')
    data = joblib.load(REF / 'dataset.joblib')
    originals = {r['race_id']: r for r in data['records'] + data['later']}
    accepted, excluded, hashes = [], [], {}
    for relative, digest in read(REF / 'dataset-manifest.json')['card_sha256'].items():
        path = ROOT / relative
        require(sha(path) == digest, 'T10_archive_hash')
        hashes[relative] = digest
        for raw in reuse.prior.readlines(path):
            if raw['race_id'] not in originals:
                continue
            old = originals[raw['race_id']]
            try:
                quotes = raw['inputs']['odds']['T-10m']
                cutoff = datetime.fromisoformat(raw['race']['start_at']) - timedelta(minutes=10)
                for bet in ('win', 'quinella'):
                    q = quotes[bet]
                    age = (cutoff - datetime.fromisoformat(q['announced_at'])).total_seconds() / 60
                    require(datetime.fromisoformat(q['cutoff']) == cutoff and 0 <= age <= 5, 'T10_time_or_staleness')
                odds = numeric(quotes['quinella'], 'quinella', old['horses'])
                wins = numeric(quotes['win'], 'win', old['horses'])
                early = numeric(raw['inputs']['odds']['T-30m']['quinella'], 'quinella', old['horses'])
                q = 1 / early; q /= q.sum()
                require(np.max(np.abs(q - old['market'])) < 1e-12, 'T10_early_market_changed')
                market = 1 / odds; market /= market.sum()
                pay = raw['result']['quinella_payout_per_100_yen']
                require(len(pay) == 1, 'T10_ambiguous_pay')
                pair = sorted([int(pay[0]['horse_no_1']), int(pay[0]['horse_no_2'])])
                require(pair == list(list(combinations(map(int, old['horses']), 2))[old['winner']]), 'T10_outcome_pair')
                r = model.base.clean(old) | {'early_market': old['market'], 'early_pl': old['pl'],
                    'market': market, 'pl': model.base.pl_pairs(1 / wins), 'prices': odds,
                    'winner': old['winner'], 'payout_yen': int(pay[0]['payout'])}
                model.matrix(r)
                accepted.append(r)
            except (KeyError, TypeError, ValueError, ResearchError) as error:
                reason = getattr(error, 'reason', 'T10_structure_' + type(error).__name__)
                if reason in ('T10_early_market_changed', 'T10_outcome_pair'):
                    raise
                excluded.append({'race_id': old['race_id'], 'reason': reason})
        print('T10_dataset_year', path.parent.name, len(accepted), flush=True)
    accepted.sort(key=lambda r: r['race_id'])
    joblib.dump(accepted, folder / 'dataset.joblib', compress=3)
    save(folder / 'dataset-manifest.json', {'races': len(accepted), 'archive_sha256': hashes,
        'dataset_sha256': sha(folder / 'dataset.joblib'), 'excluded': excluded, 'historical_publication_verified': False})
    return accepted


def probability_ci(rows, baseline):
    """同日の損失差をまとめて抽出し、対照比の損失改善95%区間を作る。"""
    days = sorted({r['race_date'] for r in rows})
    daily = {d: [0., 0.] for d in days}
    for r, b in zip(rows, baseline, strict=True):
        require(r['race_id'] == b['race_id'], 'T10_ci_roster')
        daily[r['race_date']][0] += b['loss'] - r['loss']
        daily[r['race_date']][1] += 1
    array = np.array([daily[d] for d in days])
    ix = np.random.default_rng(450).integers(0, len(days), (20000, len(days)), dtype=np.int32)
    values = []
    for i in range(0, 20000, 200):
        totals = array[ix[i:i + 200]].sum(axis=1)
        values.extend((totals[:, 0] / totals[:, 1]).tolist())
    return np.quantile(values, [.025, .975]).tolist()


def run(folder):
    """適格T10構築→逐次8fit→全比較→原本互換を実行し、失敗証跡も保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'freeze'
    try:
        initial = sources()
        previous = read(PREVIOUS / 'assessment.json')
        require(read(PREVIOUS / 'independent-verification.json')['status'] == 'passed', 'T10_previous_verification')
        require(not any(v['decision']['label'] == 'promising_historical_candidate' for g in ('historical', 'additional') for v in previous[g].values()), 'T10_branch_not_needed')
        frozen = {str(p.relative_to(ROOT)): sha(p) for p in (PREVIOUS / 'assessment.json', PREVIOUS / 'independent-verification.json',
            REF / 'dataset.joblib', REF / 'dataset-manifest.json', reuse.prior.CAP / 'inputs.jsonl.gz')}
        for year in (2023, 2024, 2025, 2026):
            path = reuse.prior.old.S0 / f'{year}_S0.joblib'
            expected = read(reuse.prior.old.S0 / 'manifest.json')['model_sha256'][path.name]
            require(sha(path) == expected, 'T10_old_model_sha')
            frozen[str(path.relative_to(ROOT))] = expected
        save(folder / 'protocol.json', {'source_sha256': initial, 'frozen_inputs_sha256': frozen, 'max_fits': 8,
            'models': ['S10', 'M10'], 'bootstrap_seed': 450, 'unknown_test': False, 'purchase_allowed': False})
        stage = 'dataset'
        records = dataset(folder)
        rows = {label: [] for label in ('S0_direct', 'S10', 'M10')}
        cells = {label + '_' + rule: [] for label in rows for rule in ('P01', 'A')}
        dev, annual, models = {}, {}, {}
        for year in (2023, 2024, 2025, 2026):
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = [r for r in records if r['race_date'].startswith(str(year))]
            require(train and test, 'T10_empty_period')
            probabilities = {}
            old_s0 = joblib.load(reuse.prior.old.S0 / f'{year}_S0.joblib')
            probabilities['S0_direct'] = [model.base.predict(old_s0, r) for r in test]
            for case in ('S10', 'M10'):
                stage = f'fit_{year}_{case}'
                print('fit_start', year, case, len(train), len(test), flush=True)
                fitted = model.fit(train, case)
                path = folder / f'{year}_{case}.joblib'
                joblib.dump(fitted, path, compress=3)
                restored = joblib.load(path)
                pp = [model.predict(restored, r) for r in test]
                require(np.array_equal(model.predict(fitted, test[0]), pp[0]), 'T10_saved_reload')
                joblib.dump(pp, folder / f'{year}_{case}_predictions.joblib', compress=3)
                probabilities[case] = pp
                models[case] = fitted
                save(folder / f'{year}_{case}.json', {'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test],
                    'model_sha256': sha(path), 'case': case, 'optimizer': fitted['optimizer']})
                print('fit_complete', year, case, fitted['optimizer'], flush=True)
                del restored
                gc.collect()
            joblib.dump(probabilities['S0_direct'], folder / f'{year}_S0_direct_predictions.joblib', compress=3)
            yr = {case: reuse.prior.old.reuse.metrics(test, pp, case) for case, pp in probabilities.items()}
            annual[str(year)] = {case: reuse.prior.old.reuse.helper.summary(rr) for case, rr in yr.items()}
            if year == 2023:
                dev = annual[str(year)]
            else:
                for case, pp in probabilities.items():
                    rows[case].extend(yr[case])
                    for r, p in zip(test, pp, strict=True):
                        choices = policy.select(p, r['prices'])
                        for rule in ('P01', 'A'):
                            cells[case + '_' + rule].append(policy.settle(r, choices[rule], r['payout_yen'], r['winner']))
            del train, probabilities
            gc.collect()
        stage = 'assessment'
        totals = {case: reuse.prior.old.reuse.helper.summary(rr) for case, rr in rows.items()}
        comparisons = {}
        for case in ('S10', 'M10'):
            ci = probability_ci(rows[case], rows['S0_direct'])
            checks = {'loss_improvement_ci_positive': ci[0] > 0,
                'every_year_loss_better': all(annual[str(y)][case]['logloss'] < annual[str(y)]['S0_direct']['logloss'] for y in (2024, 2025, 2026)),
                'hits_at_least_direct': totals[case]['hit_rate'] >= totals['S0_direct']['hit_rate']}
            comparisons[case] = {'loss_improvement_ci95': ci, 'checks': checks, 'probability_promising': all(checks.values())}
        save(folder / 'precision-rows.json', rows)
        save(folder / 'purchase-rows.json', cells)
        save(folder / 'assessment.json', {'annual': annual, 'pooled': totals, 'development': dev,
            'comparisons': comparisons, 'purchase': policy.assess(cells, historical=True), 'new_fits': 8,
            'unknown_test': False, 'purchase_allowed': False})
        stage = 'capture_replay'
        captures = reuse.prior.readlines(reuse.prior.CAP / 'inputs.jsonl.gz')
        early = {r['race_id']: r for r in captures if r['timing'] == 't_minus_30m'}
        replay, rejected = [], []
        for obs in captures:
            if obs['timing'] != 't_minus_10m':
                continue
            try:
                r = model.from_observations(early[obs['race_id']], obs)
                replay.append({'race_id': r['race_id'], 'timing': obs['timing'],
                               'probabilities': {case: model.predict(fitted, r).tolist() for case, fitted in models.items()}})
            except Exception as error:
                rejected.append({'race_id': obs['race_id'], 'reason': getattr(error, 'reason', str(error))})
        save(folder / 'capture-replay.json', {'accepted': replay, 'rejected': rejected, 'new_prerace_prediction': False})
        require(sources() == initial and all(sha(ROOT / p) == h for p, h in frozen.items()), 'T10_sources_changed')
        save(folder / 'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'new_fits': 8, 'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        print(json.dumps({'status': 'complete', 'pooled': totals, 'comparisons': comparisons, 'capture': len(replay)}), flush=True)
    except Exception as error:
        save(folder / 'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', str(error))})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/ten_minute_20261107')
    run(parser.parse_args().output)
