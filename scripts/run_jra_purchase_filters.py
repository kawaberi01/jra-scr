"""概要: S0/D0保存予測の購入限定10条件を固定し、原本オッズで比較する。
作成日: 2026-11-07
入力: spec440、D0 dataset、S0/D0保存確率、年別T30原本、公式精算。
出力: 新規run内のSHA、全選択行、20条件・対照の集計と採否。
実行例: uv run --frozen --extra ml python scripts/run_jra_purchase_filters.py
注意事項: 0fit、SQL/HTTP/実購入/既定変更なし。既使用過去の条件研究。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from datetime import datetime, timedelta
import gzip
from itertools import combinations
from pathlib import Path

import joblib
import numpy as np

import run_jra_course_chimera as reuse
from jra_srb import jra_research_purchase_filters as model

ROOT, REFERENCE = reuse.ROOT, reuse.REFERENCE
read, save, sha, require = reuse.read, reuse.save, reuse.sha, reuse.require
S0 = ROOT / 'artifacts/jra_research/current_attributes_S0_20261025'
OUTCOMES = ROOT / 'artifacts/jra_research/d0_usability_20261025_v2/official-outcomes.json'
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/440-S0D0購入限定10条件の固定検証.md'


def sources():
    """本検証の実装・仕様と再利用ローダーのSHAを固定する。"""
    return {str(p.relative_to(ROOT)): sha(p) for p in (
        SPEC, Path(__file__), Path(model.__file__), Path(reuse.__file__),
        ROOT / 'scripts/verify_jra_purchase_filters.py', ROOT / 'tests/test_jra_purchase_filters.py')}


def prices_for(records, folder):
    """SHA確認済み年別原本の全価格を元market・正解・時点と照合する。"""
    wanted = {r['race_id']: r for r in records}
    cards = read(REFERENCE / 'dataset-manifest.json')['card_sha256']
    prices, hashes = {}, {}
    for relative, digest in cards.items():
        if not any(f'\\{y}\\' in relative or f'/{y}/' in relative for y in (2023, 2024, 2025, 2026)):
            continue
        path = ROOT / relative
        require(sha(path) == digest, 'filter_card_sha')
        hashes[relative] = digest
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                raw = __import__('json').loads(line)
                key = raw['race_id']
                if key not in wanted:
                    continue
                require(key not in prices, 'filter_duplicate')
                r = wanted[key]
                quote = raw['inputs']['odds']['T-30m']['quinella']
                cutoff = datetime.fromisoformat(raw['race']['start_at']) - timedelta(minutes=30)
                require(datetime.fromisoformat(quote['announced_at']) <= datetime.fromisoformat(quote['cutoff']) == cutoff,
                        'filter_time')
                pairs = list(combinations(r['horses'], 2))
                mapping = {tuple(sorted((f"{int(p['horse_no_1']):02d}", f"{int(p['horse_no_2']):02d}"))):
                           float(p['odds']) for p in quote['pairs'] if p['status'] == 'numeric'}
                require(set(mapping) == set(pairs) and len(mapping) == len(quote['pairs']), 'filter_pair_roster')
                odds = np.array([mapping[k] for k in pairs])
                require(np.all(np.isfinite(odds)) and np.all(odds > 0), 'filter_price')
                q = 1 / odds
                q /= q.sum()
                require(np.allclose(q, r['market'], atol=1e-12, rtol=0), 'filter_market_mismatch')
                payout = raw['result']['quinella_payout_per_100_yen']
                require(len(payout) == 1, 'filter_payout_count')
                winner = sorted([int(payout[0]['horse_no_1']), int(payout[0]['horse_no_2'])])
                require(winner == [int(h) for h in pairs[r['winner']]], 'filter_winner')
                prices[key] = {'odds': odds, 'payout': int(payout[0]['payout']),
                               'announced_at': quote['announced_at'], 'cutoff': quote['cutoff'],
                               'raw_sha256': quote['raw_sha256']}
        print('price_year_complete', path.parent.name, len(prices), flush=True)
    require(set(prices) == set(wanted), 'filter_price_coverage')
    save(folder / 'price-inputs.json', {'sha256': hashes, 'matched': len(prices), 'horizon': 'T-30m',
         'market_max_abs_tolerance': 1e-12, 'historical_publication_verified': False})
    return prices


def run(folder):
    """20比較セルを変更なしに実行し、無条件対照・年別・採否を新規保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'freeze'
    try:
        initial = sources()
        save(folder / 'protocol.json', {'source_sha256': initial, 'policies': model.policies(),
            'seed': 440, 'bootstrap': 20000, 'family_cells': 20, 'new_fits': 0,
            'unknown_test': False, 'purchase_allowed': False})
        records, later, d0 = reuse.load_inputs(folder)
        records = [r for r in records + later if r['race_date'] >= '2023-01-01']
        frozen = {str(p.relative_to(ROOT)): sha(p) for p in (
            OUTCOMES, S0 / 'manifest.json', S0 / 'independent-verification.json')}
        require(read(S0 / 'independent-verification.json')['status'] == 'passed', 'filter_S0_verification')
        manifest = read(S0 / 'manifest.json')
        for filename, digest in manifest['files_sha256'].items():
            if filename.endswith('_S0.json') or filename.endswith('_S0_predictions.joblib'):
                require(sha(S0 / filename) == digest, 'filter_S0_prediction_sha')
                frozen[str((S0 / filename).relative_to(ROOT))] = digest
        outcomes = read(OUTCOMES)
        stage = 'prices'
        prices = prices_for(records, folder)
        frozen.update(read(folder / 'price-inputs.json')['sha256'])
        rows = {'S0': [], 'D0': []}
        for year in (2023, 2024, 2025, 2026):
            test = [r for r in records if r['race_date'].startswith(str(year))]
            cell = read(S0 / f'{year}_S0.json')
            require(cell['test_ids'] == [r['race_id'] for r in test], 'filter_S0_ids')
            require(all(key[:4] < str(year) for key in cell['train_ids']), 'filter_train_boundary')
            probabilities = joblib.load(S0 / f'{year}_S0_predictions.joblib')
            require(len(probabilities) == len(test), 'filter_probability_count')
            for r, ps in zip(test, probabilities, strict=True):
                price = prices[r['race_id']]
                if year >= 2024:
                    require(price['payout'] == outcomes[r['race_id']]['payout_per_100_yen'], 'filter_official_payout')
                if 'payout_yen' in r:
                    require(price['payout'] == r['payout_yen'], 'filter_dataset_payout')
                for label, p in (('S0', ps), ('D0', d0[r['race_id']])):
                    require(len(p) == len(price['odds']) and np.all(np.isfinite(p)) and np.all(p > 0)
                            and abs(float(np.sum(p)) - 1) < 1e-10, 'filter_probability')
                    index = int(np.argmax(p))
                    pairs = list(combinations(r['horses'], 2))
                    probability, odds = float(p[index]), float(price['odds'][index])
                    hit = int(index == r['winner'])
                    row = {k: r[k] for k in ('race_id', 'race_date', 'course', 'surface', 'distance')}
                    rows[label].append(row | {'model': label, 'top_pair_index': index, 'pair': list(pairs[index]),
                        'probability': probability, 'odds': odds, 'ev': probability * odds,
                        'hit': hit, 'paid_yen': price['payout'] * hit, 'official_payout_yen': price['payout'],
                        'announced_at': price['announced_at'], 'cutoff': price['cutoff'], 'raw_sha256': price['raw_sha256']})
        save(folder / 'selected-rows.json', rows)
        stage = 'assessment'
        main = {label: [r for r in rr if r['race_date'] >= '2024-01-01'] for label, rr in rows.items()}
        days = sorted({r['race_date'] for r in main['S0']})
        indices = np.random.default_rng(440).integers(0, len(days), size=(20000, len(days)), dtype=np.int32)
        entries, stakes, paids = [], [], []
        for label in ('S0', 'D0'):
            rr = main[label]
            masks = [[model.accepts(r['probability'], r['odds'], p) for r in rr] for p in model.policies()]
            s, p = model.day_arrays(rr, masks, days)
            stakes.append(s)
            paids.append(p)
            for policy, mask in zip(model.policies(), masks, strict=True):
                annual = {}
                for year in (2024, 2025, 2026):
                    subset = [(r, m) for r, m in zip(rr, mask, strict=True) if r['race_date'].startswith(str(year))]
                    annual[str(year)] = model.summarize([r for r, _ in subset], [m for _, m in subset])
                dev = [r for r in rows[label] if r['race_date'] < '2024-01-01']
                entries.append({'model': label, 'policy': policy, 'total': model.summarize(rr, mask), 'annual': annual,
                    'development_2023': model.summarize(dev, [model.accepts(r['probability'], r['odds'], policy) for r in dev]),
                    'purchased_ids': [r['race_id'] for r, buy in zip(rr, mask, strict=True) if buy]})
        intervals = model.bootstrap(np.column_stack(stakes), np.column_stack(paids), indices)
        for entry, interval in zip(entries, intervals, strict=True):
            entry['interval'] = interval
            entry['decision'] = model.decide(entry['total'], entry['annual'], interval)
        controls = {label: {'total': model.summarize(rr, [True] * len(rr)),
                    'annual': {str(y): model.summarize([r for r in rr if r['race_date'].startswith(str(y))],
                        [True] * sum(r['race_date'].startswith(str(y)) for r in rr)) for y in (2024, 2025, 2026)}}
                    for label, rr in main.items()}
        save(folder / 'assessment.json', {'entries': entries, 'controls': controls, 'opportunity_days': days,
             'family_cells': 20, 'unknown_test': False, 'new_fits': 0, 'purchase_allowed': False,
             'promising_cells': [e['model'] + '_' + e['policy']['id'] for e in entries
                                  if e['decision']['label'] == 'promising_historical_candidate']})
        require(sources() == initial and all(sha(ROOT / p) == v for p, v in frozen.items()), 'filter_changed_inputs')
        save(folder / 'manifest.json', {'status': 'complete', 'source_sha256': initial, 'frozen_inputs_sha256': frozen,
             'files_sha256': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        print('complete', [(e['model'], e['policy']['id'], e['total']['purchases'], e['total']['roi_percent'],
                            e['decision']['label']) for e in entries], flush=True)
    except Exception as error:
        save(folder / 'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', str(error))})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/purchase_filters_20261107')
    run(parser.parse_args().output)
