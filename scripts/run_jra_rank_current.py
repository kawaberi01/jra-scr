"""概要: S2順位専用モデルを固定4期間で学習し、S0/D0/市場と比較する。
作成日: 2026-11-05
入力: spec435、検算済み既存dataset・保存予測・公式精算・事前原本。
出力: 新規run内の4モデル、全スコア、固定精算、区間、採否、原本再生、SHA。
実行例: uv run --frozen --extra ml python scripts/run_jra_rank_current.py
注意事項: スコアは確率でない。SQL・レース情報HTTP・追加取得・購入・既定変更なし。
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

import run_jra_current_attributes as reuse
from jra_srb import jra_research_rank_current as model
from jra_srb.jra_research_contracts import ResearchError

ROOT, REFERENCE = reuse.ROOT, reuse.REFERENCE
read, save, sha, require, log = reuse.read, reuse.save, reuse.sha, reuse.require, reuse.log
S0 = ROOT/'artifacts/jra_research/current_attributes_S0_20261025'
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/435-S2順位専用学習の固定比較.md'
OLD_RANK = ROOT/'artifacts/jra_research/market_rank_chimera_20261024/assessment.json'


def sources():
    """今回の仕様・計算コードと再利用コードを実行前に固定する。"""
    return {**reuse.sources(), **{str(p.relative_to(ROOT)): sha(p) for p in
        (SPEC, Path(__file__), Path(model.__file__), Path(model.rank.__file__), ROOT/'scripts/verify_jra_rank_current.py')}}


def rows_for(records, values, label, outcomes):
    """スコアまたは基準分布の順位だけで、同じレースの一票を精算する。"""
    result = []
    for r, array in zip(records, values, strict=True):
        require(np.isfinite(array).all() and len(array) == len(r['market']), 'S2_evaluation_shape')
        order = np.argsort(-np.asarray(array), kind='stable')
        top, y = int(order[0]), int(r['winner'])
        hit = int(top == y)
        if r['race_date'] < '2024-01-01':
            payout = int(r['payout_yen'])
        else:
            outcome = outcomes[r['race_id']]
            a, b = model.base.core.base.pairs(len(r['horses']))[y]
            require(sorted([int(r['horses'][a]), int(r['horses'][b])]) == sorted(outcome['winner_pair']), 'S2_outcome_pair')
            payout = int(outcome['payout_per_100_yen'])
            if 'payout_yen' in r:
                require(payout == r['payout_yen'], 'S2_outcome_payout')
        result.append({k: r[k] for k in ('race_id', 'race_date', 'course', 'surface')}|
            {'distance_band': model.base.core.base.distance_band(r['distance']),
             'season': model.base.core.base.season(r['race_date']), 'label': label,
             'top_pair_index': top, 'winner_rank': int(np.flatnonzero(order == y)[0])+1,
             'hit': hit, 'paid_yen': hit*payout})
    return result


def run(folder):
    """一構成4fitと全比較を実施し、採否まで新規runへ保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = sources()
        require(all(sha(ROOT/p) == value for p, value in initial.items()), 'S2_sources')
        s0_manifest = read(S0/'manifest.json')
        require(read(S0/'independent-verification.json')['status'] == 'passed'
                and all(sha(S0/p) == value for p, value in s0_manifest['files_sha256'].items()), 'S2_S0_reference')
        require(read(reuse.CAPTURE/'verification.json')['status'] == 'passed', 'S2_capture_reference')
        frozen = {str(p.relative_to(ROOT)): sha(p) for p in
            (S0/'manifest.json', S0/'independent-verification.json', reuse.OUTCOMES, reuse.CAPTURE/'inputs.jsonl.gz', OLD_RANK)}
        save(folder/'protocol.json', {'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'max_new_fits': 4, 'cases': ['S2'], 'negative_top': 5, 'output_kind': 'rank_score_not_probability',
            'unknown_test': False, 'purchase_allowed': False, 'old_rank_selected': read(OLD_RANK)['selected']})
        records, later, d0 = reuse.reuse.load_inputs(folder)
        records = [model.base.clean(r)|{k: r[k] for k in ('winner', 'payout_yen')} for r in records]
        later = [model.base.clean(r)|{'winner': r['winner']} for r in later]
        outcomes = read(reuse.OUTCOMES)
        annual, pooled, models = {}, {k: [] for k in ('S2', 'S0', 'D0', 'market')}, {}
        for year in (2023, 2024, 2025, 2026):
            stage = f'fit_{year}'
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = later if year == 2026 else [r for r in records if r['race_date'].startswith(str(year))]
            log('S2_fit_start', year=year, train=len(train), test=len(test))
            fitted = model.fit(train)
            path = folder/f'{year}_S2.joblib'
            joblib.dump(fitted, path, compress=3)
            restored = joblib.load(path)
            values = [model.scores(restored, r) for r in test]
            s0 = joblib.load(S0/f'{year}_S0_predictions.joblib')
            s0_model = joblib.load(S0/f'{year}_S0.joblib')
            require(np.array_equal(fitted['scale'], s0_model['scale']) and fitted['contexts'] == s0_model['contexts']
                    and fitted['context_counts'] == s0_model['context_counts'], 'S2_S0_scale_or_context')
            require(read(S0/f'{year}_S0.json')['test_ids'] == [r['race_id'] for r in test], 'S2_S0_roster')
            for i in (0, len(test)//2, len(test)-1):
                require(np.array_equal(model.scores(fitted, test[i]), values[i])
                        and np.array_equal(model.scores(restored, test[i]|{'winner': -1, 'payout_yen': -1, 'x': 'poison'}), values[i]), 'S2_reload_or_result')
            rows = {label: rows_for(test, arrays, label, outcomes) for label, arrays in
                    [('S2', values), ('S0', s0), ('D0', [d0[r['race_id']] for r in test]), ('market', [r['market'] for r in test])]}
            annual[str(year)] = {k: model.summary(v) for k, v in rows.items()}
            models[path.name] = sha(path)
            joblib.dump(values, folder/f'{year}_S2_scores.joblib', compress=3)
            save(folder/f'{year}_S2.json', {'train_ids': [r['race_id'] for r in train],
                'test_ids': [r['race_id'] for r in test], 'model_sha256': models[path.name],
                'S0_scale_context_equal': True, 'rows': rows, 'summary': annual[str(year)]})
            if year == 2023:
                a, b = annual['2023']['S2'], annual['2023']['S0']
                selected = a['hits'] > b['hits'] and a['roi_percent'] >= b['roi_percent']
                save(folder/'selection.json', {'S2_selected': selected, 'confirmation_used': False, 'summary': annual['2023']})
            else:
                for key in pooled:
                    pooled[key].extend(rows[key])
            log('S2_fit_complete', year=year, summary=annual[str(year)])
            del train, restored, values, s0, s0_model
            gc.collect()
        stage = 'assessment'
        totals = {k: model.summary(v) for k, v in pooled.items()}
        intervals = {k: model.comparison_ci(pooled['S2'], pooled[k]) for k in ('S0', 'D0', 'market')}
        checks = {'development_selected': selected,
            'S0_hit_difference_ci_positive': intervals['S0']['hit_rate_difference_ci95'][0] > 0,
            'roi_at_least_S0': totals['S2']['roi_percent'] >= totals['S0']['roi_percent'],
            'annual_hit_drop_within_half_pp': all(annual[str(y)]['S2']['hit_rate'] >= annual[str(y)]['S0']['hit_rate']-.005 for y in (2024, 2025, 2026))}
        d0_checks = {'D0_hit_difference_ci_positive': intervals['D0']['hit_rate_difference_ci95'][0] > 0,
                     'roi_at_least_D0': totals['S2']['roi_percent'] >= totals['D0']['roi_percent']}
        save(folder/'assessment.json', {'annual': annual, 'pooled': totals, 'intervals': intervals,
            'checks': checks, 'D0_checks': d0_checks, 'promising_S0_improvement': all(checks.values()),
            'promising_D0_replacement': all(checks.values()) and all(d0_checks.values()),
            'grouped': {k: model.grouped(v) for k, v in pooled.items()}, 'output_kind': 'rank_score_not_probability',
            'unknown_test': False, 'purchase_allowed': False, 'default_changed': False})
        stage = 'capture_replay'
        accepted, rejected = [], []
        with gzip.open(reuse.CAPTURE/'inputs.jsonl.gz', 'rt', encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                obs = json.loads(line)
                try:
                    r = model.base.from_capture(obs)
                    values = model.scores(fitted, r)
                    accepted.append({'observation_index': index, 'race_id': r['race_id'], 'timing': obs['timing'],
                        'horses': r['horses'], 'scores': values.tolist(),
                        'pair_order': np.argsort(-values, kind='stable').tolist()})
                except (ResearchError, ValueError, KeyError) as error:
                    rejected.append({'observation_index': index, 'race_id': obs['race_id'],
                                     'reason': getattr(error, 'reason', type(error).__name__)})
        save(folder/'capture-replay.json', {'accepted': accepted, 'rejected': rejected,
            'accepted_races': len({r['race_id'] for r in accepted}), 'output_kind': 'rank_score_not_probability',
            'performance_test': False, 'live_prediction_saved': False})
        require(sources() == initial and all(sha(ROOT/p) == v for p, v in initial.items())
                and all(sha(ROOT/p) == v for p, v in frozen.items()), 'S2_sources_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
            'model_sha256': models, 'new_fits': 4, 'D0_refits': 0, 'S0_refits': 0,
            'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        log('S2_complete', pooled=totals, checks=checks, D0_checks=d0_checks, accepted=len(accepted), rejected=len(rejected))
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/jra_research/rank_current_S2_20261105')
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
