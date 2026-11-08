"""概要: 当日属性と連続距離のH2拡張を2023年で選抜し、翌3年で確認する。
作成日: 2026-10-24
入力: spec365、保存済み履歴/市場/カード属性とH2年別モデル。
出力: 新規runの属性結合、係数、全分布、選抜/追加有望判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_attribute_chimera.py --output artifacts/jra_research/market_attribute_chimera_20261024
注意事項: SQL/HTTP/実購入なし。欠測枠は中立値+明示フラグ。過去の探索。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from collections import Counter
import gc
import gzip
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

import run_jra_rank_chimera as previous
from jra_srb import jra_research_attribute_chimera as model


ROOT, BASE, LATER = previous.ROOT, previous.BASE, previous.LATER
SPEC = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/365-当日属性と連続距離の条件共有.md'
CARDS = ROOT/'data/training/jra_o1o2_asof_v2/20261002-raw-v2-complete'
ORDER = ('H2', 'D0', 'D1', 'D2')
save, read, sha, log = previous.old.prior.save, previous.read, previous.old.prior.sha, previous.old.prior.log
require = previous.old.require


def source_hashes():
    """仕様と新旧計算コードを初期化時に固定する。"""
    paths = (SPEC, Path(__file__), Path(model.__file__), Path(model.core.__file__), Path(model.core.base.__file__))
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def public_attributes(race, horses):
    """既存カードの同一馬集合へ公開属性を馬番順に結合する。

    Args:
        race: 保存済みv2カードと履歴特徴。
        horses: 正規化済みの出走馬番号順。
    Returns:
        6馬属性、競走条件フラグ、欠測枠件数。
    Raises:
        ResearchError: 馬番号重複/不足、年齢/性別や競走フラグの矛盾。
    """
    runners = {}
    for row in race['inputs']['runners']:
        raw = str(row['horse_no'])
        if not raw.isdigit():
            continue
        number = f'{int(raw):02d}'
        require(number not in runners, 'attribute_duplicate_card_horse')
        runners[number] = row
    require(set(horses).issubset(runners), 'attribute_card_roster_missing')
    values, race_flags, missing = [], [], 0
    for number in horses:
        row = runners[number]
        h = row['history_features']
        age, female, gelding = model.sex_age_attributes(row.get('sex_age'))
        sexes = [float(h[k]) for k in ('sex_female', 'sex_gelding', 'sex_male')]
        expected_sex = [female, gelding, int(not female and not gelding)]
        require(all(v in (0, 1) for v in sexes) and (sum(sexes) == 0 or sexes == expected_sex), 'attribute_card_sex_conflict')
        require(float(h['age_scaled']) == 0 or abs(float(h['age_scaled'])-min(age, 1.)) < 1e-6, 'attribute_card_age_conflict')
        frame = row.get('frame_no')
        known = frame is not None and str(frame).isdigit() and 1 <= int(frame) <= 8
        missing += int(not known)
        values.append([age, female, gelding, int(frame)/8 if known else .5, int(number)/len(horses), float(not known)])
        race_flags.append(tuple(float(h[k]) for k in ('is_newcomer', 'is_maiden', 'is_open_or_stakes')))
    require(len(set(race_flags)) == 1, 'attribute_card_race_flags_disagree')
    return np.asarray(values, dtype=np.float32), np.asarray(race_flags[0], dtype=np.float32), missing


def prepare(folder):
    """既存派生特徴にカードの当日属性だけを追加し、結果を新入力へ入れない。"""
    for data_folder in (BASE, LATER):
        manifest = read(data_folder/'dataset-manifest.json')
        require(sha(data_folder/'dataset.joblib') == manifest['sha256'], 'attribute_dataset_sha')
    records = joblib.load(BASE/'dataset.joblib')['records']
    later = joblib.load(LATER/'dataset.joblib')['records']
    wanted = {r['race_id']: r for r in records+later}
    require(len(wanted) == len(records)+len(later), 'attribute_duplicate_input')
    accepted, coverage, hashes = set(), {}, {}
    for year in range(2020, 2027):
        path = CARDS/str(year)/'races.jsonl.gz'
        manifest = read(path.parent/'manifest.json')
        actual = sha(path)
        require(actual == manifest['files']['races.jsonl.gz']['sha256'], 'attribute_card_dataset_sha')
        hashes[str(path.relative_to(ROOT))] = actual
        counts = Counter()
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                import json
                source = json.loads(line)
                key = source['race_id']
                if key not in wanted:
                    continue
                require(key not in accepted, 'attribute_duplicate_source_race')
                record = wanted[key]
                attrs, flags, missing = public_attributes(source, record['horses'])
                record['attributes'], record['race_flags'] = attrs, flags
                accepted.add(key)
                counts.update(races=1, runners=len(attrs), missing_frames=missing)
        coverage[str(year)] = dict(counts)
        log('attributes_joined', year=year, **counts)
    require(accepted == set(wanted), 'attribute_join_incomplete')
    joblib.dump({'records': records, 'later': later, 'protocol': model.PROTOCOL}, folder/'dataset.joblib', compress=3)
    save(folder/'dataset-manifest.json', {'sha256': sha(folder/'dataset.joblib'), 'coverage': coverage,
        'card_sha256': hashes, 'source_dataset_sha256': sha(BASE/'dataset.joblib'), 'later_source_sha256': sha(LATER/'dataset.joblib'),
        'history_card_publication_verified': False, 'source_sha256': source_hashes()})
    return records, later


def predict(fitted, record):
    """旧基準H2か追加属性モデルを入力定義に従って推論する。"""
    return model.core.predict(fitted, model.core.clean(record)) if fitted['protocol'] == model.core.PROTOCOL else model.predict(fitted, model.clean(record))


def measure(records, fitted, label):
    """全予測分布と、同じ集合の確率/1位選択成績を返す。"""
    rows, distributions = [], []
    for r in records:
        p = np.asarray(r['market']) if fitted is None else predict(fitted, r)
        y = r['winner']
        rows.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'label': label,
            'course': r['course'], 'surface': r['surface'], 'distance_band': model.core.base.distance_band(r['distance']),
            'season': model.core.base.season(r['race_date']), 'loss': float(-np.log(p[y])), 'hit': int(np.argmax(p) == y),
            'brier': float((p@p-2*p[y]+1)/len(p))})
        distributions.append(p)
    return rows, distributions


def cell(folder, train, test, year, case):
    """旧H2は再利用、追加案だけ学習してモデル/教師ID/全分布を保存する。"""
    log('attribute_fit', case=case, year=year, train_races=len(train))
    fitted = previous.load_reference(year) if case == 'H2' else model.fit(train, case)
    path = folder/f'{year}_{case}.joblib'
    joblib.dump(fitted, path, compress=3)
    restored = joblib.load(path)
    rows, distributions = measure(test, restored, case)
    for i in (0, len(test)//2, len(test)-1):
        p = predict(fitted, test[i])
        require(np.array_equal(p, distributions[i]), 'attribute_reload_mismatch')
        require(np.array_equal(p, predict(restored, {**test[i], 'winner': -1, 'payout_yen': -1})), 'attribute_result_dependency')
    joblib.dump(distributions, folder/f'{year}_{case}_predictions.joblib', compress=3)
    save(folder/f'{year}_{case}.json', {'case': case, 'year': year, 'trained_through': fitted['trained_through'],
        'model_sha256': sha(path), 'train_ids': [r['race_id'] for r in train], 'test_ids': [r['race_id'] for r in test],
        'rows': rows, 'summary': previous.old.prior.summary(rows), 'reused_H2': case == 'H2'})
    log('attribute_evaluated', case=case, year=year, **previous.old.prior.summary(rows))
    gc.collect()
    return rows


def run(folder, dataset=None, prepare_only=False):
    """公開属性/距離案を開発年で選抜し、同じ固定案だけを3年確認する。

    Notes:
        入力/計算不整合はfailure.jsonへ記録して停止。確認期間で別案を選び直さない。
    """
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        initial = source_hashes()
        save(folder/'protocol.json', {'protocol': model.PROTOCOL, 'source_sha256': initial, 'cases': list(ORDER),
            'selection_year': 2023, 'confirmation_years': [2024, 2025, 2026], 'max_new_fits': 6, 'unknown_test': False})
        stage = 'attributes'
        if dataset is None:
            records, later = prepare(folder)
        else:
            import shutil
            manifest = read(dataset.parent/'dataset-manifest.json')
            require(sha(dataset) == manifest['sha256'] and manifest['source_sha256'] == initial, 'attribute_reused_dataset_contract')
            loaded = joblib.load(dataset)
            require(loaded['protocol'] == model.PROTOCOL, 'attribute_reused_dataset_protocol')
            records, later = loaded['records'], loaded['later']
            shutil.copy2(dataset, folder/'dataset.joblib')
            save(folder/'dataset-manifest.json', manifest)
        # 初回の外部属性追加では全件入力受入を学習より先に分離できる。
        for record in records+later:
            model.matrix(model.clean(record), 'D2')
        save(folder/'input-acceptance.json', {'status': 'passed', 'records': len(records), 'later': len(later),
            'all_public_matrices_checked': True, 'source_sha256': initial})
        if prepare_only:
            log('attribute_inputs_accepted', records=len(records), later=len(later))
            return
        train = [r for r in records if r['race_date'] < '2023-01-01']
        test = [r for r in records if r['race_date'].startswith('2023')]
        stage = 'development'
        development = {c: previous.old.prior.summary(cell(folder, train, test, 2023, c)) for c in ORDER}
        minimum = min(v['logloss'] for v in development.values())
        chosen = next(c for c in ORDER if development[c]['logloss'] <= minimum+1e-8)
        save(folder/'selection.json', {'chosen': chosen, 'development': development,
            'criterion': '2023_logloss_only_tie_simple', 'confirmation_used': False})
        log('attribute_selection_frozen', chosen=chosen)
        stage = 'confirmation'
        annual, candidate_all, reference_all, market_all = {}, [], [], []
        for year in (2024, 2025):
            train = [r for r in records if r['race_date'] < f'{year}-01-01']
            test = [r for r in records if r['race_date'].startswith(str(year))]
            baseline = cell(folder, train, test, year, 'H2')
            candidate = baseline if chosen == 'H2' else cell(folder, train, test, year, chosen)
            market, _ = measure(test, None, 'M0')
            annual[str(year)] = {k: previous.old.prior.grouped(v) for k, v in [('selected', candidate), ('H2', baseline), ('market', market)]}
            candidate_all.extend(candidate)
            reference_all.extend(baseline)
            market_all.extend(market)
        stage = 'final_fit'
        final = previous.load_reference(2026) if chosen == 'H2' else model.fit(records, chosen)
        joblib.dump(final, folder/'final_model.joblib', compress=3)
        restored = joblib.load(folder/'final_model.joblib')
        require(np.array_equal(predict(final, later[0]), predict(restored, later[0])), 'attribute_final_reload')
        candidate, distributions = measure(later, restored, chosen)
        baseline, _ = measure(later, previous.load_reference(2026), 'H2')
        market, _ = measure(later, None, 'M0')
        joblib.dump(distributions, folder/'2026_selected_predictions.joblib', compress=3)
        save(folder/'2026_selected.json', {'rows': candidate, 'test_ids': [r['race_id'] for r in later]})
        annual['2026'] = {k: previous.old.prior.grouped(v) for k, v in [('selected', candidate), ('H2', baseline), ('market', market)]}
        candidate_all.extend(candidate)
        reference_all.extend(baseline)
        market_all.extend(market)
        summary, base_summary = previous.old.prior.summary(candidate_all), previous.old.prior.summary(reference_all)
        ci = previous.old.prior.comparison_ci(candidate_all, reference_all)
        checks = {'pooled_loss_better_than_H2': summary['logloss'] < base_summary['logloss'],
            'pooled_H2_loss_ci_positive': ci['loss_improvement_ci95'][0] > 0,
            'market_loss_better_each_year': all(v['selected']['all']['logloss'] < v['market']['all']['logloss'] for v in annual.values()),
            'pooled_hit_rate_not_worse_than_H2': summary['hit_rate'] >= base_summary['hit_rate']}
        save(folder/'assessment.json', {'selected': chosen, 'confirmation': annual, 'pooled_selected': summary, 'pooled_H2': base_summary,
            'vs_H2_ci': ci, 'vs_market_ci': previous.old.prior.comparison_ci(candidate_all, market_all),
            'additional_promising_checks': checks, 'replace_H2_as_research_candidate': all(checks.values()),
            'top1_superiority_evidence': ci['hit_rate_difference_ci95'][0] > 0, 'unknown_test': False, 'production_adoption': False})
        require(source_hashes() == initial, 'attribute_sources_changed')
        save(folder/'model-manifest.json', {'protocol': model.PROTOCOL, 'selected': chosen, 'model_sha256': sha(folder/'final_model.joblib'),
            'trained_through': final['trained_through'], 'train_ids': [r['race_id'] for r in records], 'source_sha256': initial,
            'dataset_sha256': sha(folder/'dataset.joblib'), 'assessment_sha256': sha(folder/'assessment.json')})
        save(folder/'verification.json', {'status': 'passed', 'reload_equal': True, 'result_ignored': True,
            'attribute_join_complete': True, 'selection_development_only': True, 'sources_unchanged': True})
        log('attribute_complete', selected=chosen, checks=checks, pooled=summary, H2=base_summary)
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    with threadpool_limits(limits=1):
        args = parser.parse_args()
        run(args.output, args.dataset, args.prepare_only)
