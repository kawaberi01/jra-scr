"""概要: J23を当時以前の教師だけで再学習し、2021〜2023年の東京中山秋を検証する。
作成日: 2026-10-23
入力: 既定spec325、指定末年までの2020年以降T30市場JSON、2003年以降の固定SQL RA/SE原文。
出力: 新規dirのprotocol/coverage/除外/月次モデル/ledger/results/verification。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/backtest_j23_early_autumn_20261023.py --output artifacts/jra_research/j23_early_autumn_20261023
注意事項: SQLはSELECT専用。新規取得/実購入なし。既定検証は18fit。別診断から末年を指定して特徴生成関数を再利用できる。
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gc
import gzip
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from jra_srb import jra_research_chimera_thirty_features as features
from jra_srb import jra_research_chimera_thirty_model as learner
from jra_srb import jra_research_chimera_thirty as original
from jra_srb.jra_research_contracts import ResearchError, timestamp
from jra_srb.jra_research_history import HistoryConfig
from jra_srb.jra_research_r1_live import LiveAnnualReader

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / 'data/training/jra_o1o2_asof_v2/20261002-raw-v2-complete'
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/325-J23の2021年から2023年秋の固定遡及検証.md'
MONTHS = [f'{year}-{month:02d}' for year in (2021, 2022, 2023) for month in (9, 10, 11)]


def save(path, value):
    """新規JSONをUTF-8/LF・非有限数値拒否で排他保存する。"""
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def require(condition, reason):
    """検証契約違反は後続処理を止める。"""
    if not condition:
        raise ResearchError(reason)


def markets(output, end_year=2023):
    """2020〜指定末年の保存市場を時刻・馬集合・精算組で検査する。

    Args:
        output: 除外理由と元ファイルSHAを新規保存するフォルダー。
        end_year: 読み込む末年。既定2023で旧検証の範囲を維持する。
    Returns:
        tuple: 適格市場を競走キーで引く辞書と元ファイルSHA辞書。
    Raises:
        ResearchError: 元ファイルSHAがmanifestと一致しない場合。
    Notes:
        不適格市場は理由付きで隔離し、既存ファイルは上書きしない。
    """
    from jra_v91_model import numeric_market

    result, excluded, hashes = {}, [], {}
    for year in range(2020, end_year+1):
        path = DATA / str(year) / 'races.jsonl.gz'
        manifest = json.loads((path.parent/'manifest.json').read_text(encoding='utf-8'))
        actual = original.sha(path)
        require(actual == manifest['files']['races.jsonl.gz']['sha256'], 'early_dataset_hash')
        hashes[str(path.relative_to(ROOT))] = actual
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                value = json.loads(line)
                key = value['race_id']
                try:
                    require(key not in result, 'early_duplicate_race')
                    snapshot = value['inputs']['odds']['T-30m']
                    w, q = snapshot['win'], snapshot['quinella']
                    require(w is not None and q is not None, 'early_missing_market')
                    cutoff = timestamp(value['race']['start_at'])-timedelta(minutes=30)
                    for market in (w, q):
                        require(timestamp(market['announced_at']) <= timestamp(market['cutoff']) == cutoff,
                                'early_market_cutoff')
                    win = {f'{int(k):02d}': v for k, v in numeric_market(w, 'win').items()}
                    pair = {tuple(f'{int(h):02d}' for h in k): v for k, v in numeric_market(q, 'quinella').items()}
                    horses = sorted(win, key=int)
                    keys = list(combinations(horses, 2))
                    require(len(horses) >= 8 and set(pair) == set(keys), 'early_incomplete_market')
                    payouts = value['result']['quinella_payout_per_100_yen']
                    require(len(payouts) == 1, 'early_ambiguous_settlement')
                    pay = payouts[0]
                    winning = tuple(sorted((f'{int(pay["horse_no_1"]):02d}', f'{int(pay["horse_no_2"]):02d}')))
                    require(winning in pair and type(pay['payout']) is int and pay['payout'] > 0,
                            'early_invalid_settlement')
                    ranks = {f'{int(k):02d}': int(v) for k, v in value['result']['ranks_by_horse'].items()}
                    require(set(ranks) == set(horses) and sorted(ranks.values()) == list(range(1, len(horses)+1)),
                            'early_rank_roster')
                    require(tuple(sorted(k for k, v in ranks.items() if v <= 2)) == winning,
                            'early_winning_pair')
                    prices = np.asarray([pair[k] for k in keys])
                    market = 1/prices
                    market /= market.sum()
                    result[key] = {'horses': horses, 'ranks': ranks, 'winner_horses': winning,
                        'market': market, 'prices': prices, 'pl': features.pl_pairs(np.asarray([1/win[k] for k in horses])),
                        'payout_yen': pay['payout'], 'market_sha256': q['raw_sha256'], 'win_sha256': w['raw_sha256']}
                except (ResearchError, KeyError, TypeError, ValueError) as error:
                    excluded.append({'race_key': key, 'stage': 'market',
                                     'reason': error.reason if isinstance(error, ResearchError) else 'early_market_structure'})
        print(json.dumps({'stage': 'markets', 'year': year, 'accepted': len(result), 'excluded': len(excluded)}), flush=True)
    save(output/'market-excluded.json', excluded)
    save(output/'data-sha256.json', hashes)
    return result, hashes


def prepare(output, price, end_year=2023):
    """2003〜指定末年の固定原文を一巡し、各日結果反映前の元特徴を生成する。

    Args:
        output: SQL preflight・年別coverage・除外理由の新規保存先。
        price: marketsで検査済みの市場と精算情報。
        end_year: 履歴と評価入力の末年。既定2023。
    Returns:
        list: 時系列の公開特徴・市場・分離された正解/精算情報。
    Raises:
        ResearchError: SQL年digest、馬場、特徴形状、対象末日の不整合。
    Notes:
        SQLはSELECT専用で原文を永続保存しない。同日全予測の特徴生成後に履歴更新する。
    """
    audit = json.loads((features.old.AUDIT/'audit.json').read_text(encoding='utf-8'))
    states, records, coverage, rejected = features.previous.TwentyStates(), [], {}, []
    config = HistoryConfig.load(ROOT/'configs/research/history_sql_v1.json')
    with LiveAnnualReader(config) as reader:
        save(output/'sql-preflight.json', reader.preflight())
        for year in range(2003, end_year+1):
            raw, report = reader.year_before(year, f'{end_year+1}-01-01')
            require(report['input_digest'] == audit['annual'][str(year)]['source_audit']['input_digest'],
                    'early_annual_digest_changed')
            daily, counts = defaultdict(list), Counter()
            for key, source in sorted(raw.items()):
                race, reason = features.old.native.parse_race(key, source)
                if reason is not None:
                    counts['native_excluded_'+str(reason)] += 1
                    if key in price:
                        rejected.append({'race_key': key, 'stage': 'native', 'reason': reason})
                    continue
                ra = source['RA'][2]
                seconds = {r['horse_no']: features.old.clock_seconds(source['SE'][r['horse_no']][2][338:342])
                           for r in race['runners']}
                going = features.old.native.number(ra[888:889] if race['surface'] == 0 else ra[889:890])
                require(going in (1, 2, 3, 4), 'early_history_going')
                laps = [features.old.native.number(ra[890+i*3:893+i*3])/10 for i in range(25)]
                race['closing_total'] = sum([v for v in laps if v > 0][-3:]) if race['pace'] is not None else None
                daily[race['day']].append((race, seconds, going))
                counts['normal_history'] += 1
            for day, updates in sorted(daily.items()):
                for race, _, _ in updates:
                    key = race['key']
                    if key not in price:
                        continue
                    p = price[key]
                    horses = [r['horse_no'] for r in race['runners']]
                    if horses != p['horses'] or any(r['rank'] != p['ranks'][r['horse_no']] for r in race['runners']):
                        rejected.append({'race_key': key, 'stage': 'native_market', 'reason': 'early_native_roster_or_rank'})
                        continue
                    public = states.public(race)
                    x = np.column_stack((public['x'], public['extra'][:, 20:23])).astype(np.float32)
                    require(x.shape == (len(horses), 12), 'early_feature_shape')
                    winner = list(combinations(horses, 2)).index(p['winner_horses'])
                    record = {'race_key': key, 'race_date': day, 'x': x, 'horses': p['horses'],
                        'basic': states.legacy_features(race)[:, features.old.residual.BASIC].astype(np.float32),
                        'addition': np.empty((len(x), 0)), 'styles': np.zeros(len(x)), 'density': 0.,
                        'group': race['surface']*2+int(race['distance'] >= 2000), 'winner': winner,
                        **{k:p[k] for k in ('market', 'prices', 'pl', 'payout_yen', 'market_sha256', 'win_sha256')}}
                    records.append(record)
                    counts['records'] += 1
                states.update_day(updates)
            coverage[str(year)] = {'input_digest': report['input_digest'], 'counts': dict(counts)}
            save(output/f'coverage-{year}.json', coverage[str(year)])
            print(json.dumps({'stage': 'features', 'year': year, 'records': len(records)}), flush=True)
            del raw, daily
            gc.collect()
    used = {r['race_key'] for r in records}
    for key in set(price)-used-{r['race_key'] for r in rejected}:
        rejected.append({'race_key': key, 'stage': 'native', 'reason': 'early_no_native_source'})
    save(output/'feature-excluded.json', rejected)
    records.sort(key=lambda r:(r['race_date'],r['race_key']))
    require(records and max(r['race_date'] for r in records) < f'{end_year+1}-01-01', 'early_future_records')
    return records


def statistics(rows):
    """元会計に日末DD・上位3除外と固定seedの日bootstrapを付ける。"""
    if not rows:
        return {'races': 0, 'roi': None}
    summary = original.summary(rows)
    daily = defaultdict(lambda: [0, 0])
    for r in rows:
        daily[r['race_date']][0] += r['stake']
        daily[r['race_date']][1] += r['payout']
    a = np.asarray(list(daily.values()), dtype=float)
    c = np.r_[0, np.cumsum(a[:, 1]-a[:, 0])]
    summary['max_drawdown_day_end_yen'] = int(np.max(np.maximum.accumulate(c)-c))
    summary['profit_yen'] = summary['payout']-summary['stake']
    summary['roi_without_top3'] = (summary['payout']-sum(sorted((r['payout'] for r in rows), reverse=True)[:3]))/summary['stake'] if summary['stake'] else None
    summary['roi_ci95'] = None
    if summary['stake']:
        rng, samples = np.random.default_rng(325), []
        for _ in range(20000):
            total = a[rng.integers(0, len(a), len(a))].sum(axis=0)
            if total[0]: samples.append(total[1]/total[0])
        summary['roi_ci95'] = np.quantile(samples, [.025, .975]).tolist()
    summary['minimum_gate_passed'] = bool(summary['bets'] >= 100 and summary['buy_days'] >= 30
        and summary['hits'] >= 10 and summary['roi'] is not None and summary['roi'] >= 1.05
        and summary['roi_ci95'] and summary['roi_ci95'][0] > 1)
    return summary


def run(output):
    """事前契約を保存し、9月次の過去限定学習・測定・会計を実行する。"""
    output.mkdir(parents=True, exist_ok=False)
    stage = 'protocol'
    try:
        save(output/'protocol.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'spec_sha256': original.sha(SPEC), 'months': MONTHS, 'train_start': '2020-01-01',
            'cases': ['J23', 'R1', 'M0'], 'scope': 'tokyo_nakayama_autumn',
            'history_start': '2003-01-01', 'fit_limit': 18, 'unknownness_claim': False,
            'source_sha256': {str(Path(m.__file__).relative_to(ROOT)): original.sha(Path(m.__file__))
                              for m in (features, learner, features.previous, features.old, features.old.native)}})
        stage = 'market_inputs'
        price, hashes = markets(output)
        stage = 'native_features'
        records = prepare(output, price)
        del price
        (output/'cells').mkdir()
        ledger, fit_count = [], 0
        for month in MONTHS:
            stage = 'fit_'+month
            train = [r for r in records if '2020-01-01' <= r['race_date'] < month+'-01']
            test = [r for r in records if r['race_date'][:7] == month and r['race_key'][8:10] in ('05', '06')]
            require(bool(test) and len(train) >= 100, 'early_empty_fold')
            for case in ('J23', 'R1', 'M0'):
                if case == 'M0':
                    model = {'case': 'M0', 'trained_through': max(r['race_date'] for r in train), 'train_races': len(train)}
                else:
                    model = learner.fit(train, case)
                    fit_count += 1
                require(model['trained_through'] < month+'-01', 'early_training_leakage')
                model_path = output/'cells'/f'{month}_{case}.joblib'
                joblib.dump(model, model_path)
                restored = joblib.load(model_path)
                with threadpool_limits(limits=1):
                    predictions = [learner.predict(restored, learner.clean_record(r)) for r in test]
                    for index in sorted({0, len(test)//2, len(test)-1}):
                        mutated = {**test[index], 'winner': 999, 'payout_yen': 999999}
                        require(np.array_equal(predictions[index], learner.predict(restored, learner.clean_record(mutated))),
                                'early_result_dependency')
                rows = [original.measure(r, pred) for r, pred in zip(test, predictions, strict=True)]
                for row in rows:
                    row.update(model=case, month=month)
                cell = {'month': month, 'case': case, 'trained_through': model['trained_through'],
                    'train_races': len(train), 'test_races': len(test), 'model_sha256': original.sha(model_path),
                    'rows': rows}
                save(output/'cells'/f'{month}_{case}.json', cell)
                ledger.extend(rows)
                print(json.dumps({'stage':'evaluated', 'month':month, 'case':case,
                                  'train_races':len(train), 'test_races':len(test)}), flush=True)
        stage = 'summaries'
        save(output/'ledger.json', ledger)
        results = {}
        for case in ('J23', 'R1', 'M0'):
            rows = [r for r in ledger if r['model'] == case]
            results[case] = {'all': statistics(rows),
                'years': {str(y):statistics([r for r in rows if r['race_date'].startswith(str(y))]) for y in (2021,2022,2023)},
                'venues': {v:statistics([r for r in rows if r['race_key'][8:10] == code]) for v,code in [('tokyo','05'),('nakayama','06')]}}
        for path, value in hashes.items():
            require(original.sha(ROOT/path) == value, 'early_source_changed')
        save(output/'results.json', results)
        save(output/'verification.json', {'status':'passed', 'fits':fit_count, 'cells':27,
            'future_training_rows':0, 'source_unchanged':True, 'is_unseen_trial':False,
            'production_adoption':False})
        print(json.dumps({'status':'complete','results':results},ensure_ascii=False),flush=True)
    except Exception as error:
        save(output/'failure.json', {'status':'failed','stage':stage,
            'reason':error.reason if isinstance(error,ResearchError) else type(error).__name__})
        raise


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT/'scripts'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
