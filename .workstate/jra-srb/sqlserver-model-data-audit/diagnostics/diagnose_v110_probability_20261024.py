"""概要: 保存済みV110の確率帯・順位・購入選択と実的中率を診断する。
作成日: 2026-10-24
入力: spec330のpredictions.jsonl.gz、spec335。引数--sourceと--output。
出力: 新規出力先のdiagnosis.json、selection-ledger.json、verification.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/diagnose_v110_probability_20261024.py
注意事項: 学習・外部通信・本番変更なし。既存出力先があれば停止する。区間は探索的。
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


EDGES = np.array([0, .01, .02, .03, .05, .10, .20, .30, .50, 1.000000001])


def summary(items):
    """選択点集合の予測・市場確率と二値的中頻度を集計する。"""
    n = len(items)
    if not n:
        return {'n': 0, 'hits': 0, 'hit_rate': None, 'mean_probability': None}
    probabilities = np.array([r['p'] for r in items])
    hits = sum(r['hit'] for r in items)
    return {'n': n, 'hits': hits, 'hit_rate': hits/n,
            'expected_hits': float(probabilities.sum()),
            'mean_probability': float(probabilities.mean()),
            'mean_market_probability': float(np.mean([r['market_p'] for r in items])),
            'mean_odds': float(np.mean([r['odds'] for r in items])),
            'median_odds': float(np.median([r['odds'] for r in items])),
            'median_probability': float(np.median(probabilities)),
            'mean_rank': float(np.mean([r['rank'] for r in items])),
            'median_rank': float(np.median([r['rank'] for r in items]))}


def bands(items):
    """事前固定の確率帯ごとに件数と的中頻度を返す。"""
    grouped = [[] for _ in range(len(EDGES)-1)]
    for row in items:
        i = int(np.searchsorted(EDGES, row['p'], side='right')-1)
        grouped[i].append(row)
    return [{'lower_inclusive': float(EDGES[i]), 'upper_exclusive': min(float(EDGES[i+1]), 1.),
             **summary(values)} for i, values in enumerate(grouped)]


def day_ci(items, dates, draws, probability_key):
    """開催日を同時再抽出し実的中率と平均予測確率の差の区間を求める。"""
    totals = defaultdict(lambda: np.zeros(3))
    for row in items:
        totals[row['date']] += [row['hit'], row[probability_key], 1]
    a = np.array([totals[d] for d in dates])
    sampled = a[draws].sum(axis=1)
    valid = sampled[:, 2] > 0
    delta = (sampled[valid, 0]-sampled[valid, 1])/sampled[valid, 2]
    return {'observed_minus_predicted': float((a[:, 0].sum()-a[:, 1].sum())/a[:, 2].sum()),
            'day_bootstrap_ci95': np.quantile(delta, [.025, .975]).tolist()}


def rate_difference(first, second, dates, draws):
    """異なる選択集合の的中率差を同じ開催日抽出で比較する。"""
    arrays = []
    observed = []
    for rows in (first, second):
        totals = defaultdict(lambda: np.zeros(2))
        for row in rows:
            totals[row['date']] += [row['hit'], 1]
        a = np.array([totals[d] for d in dates])
        arrays.append(a[draws].sum(axis=1))
        observed.append(a[:, 0].sum()/a[:, 1].sum())
    valid = (arrays[0][:, 1] > 0) & (arrays[1][:, 1] > 0)
    differences = arrays[0][valid, 0]/arrays[0][valid, 1]-arrays[1][valid, 0]/arrays[1][valid, 1]
    return {'hit_rate_difference': float(observed[0]-observed[1]),
            'day_bootstrap_ci95': np.quantile(differences, [.025, .975]).tolist()}


def run(source, output):
    """保存分布を検査して固定診断を実行し、新規ファイルへ保存する。

    Args:
        source: spec330の保存成果物フォルダー。
        output: 新規に作る診断フォルダー。
    Raises:
        AssertionError: 分布・レース集合・元購入集計に不整合がある場合。
        FileExistsError: 出力先が既に存在する場合。
    """
    input_path = source/'predictions.jsonl.gz'
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    all_pairs, selected = [], []
    top = {m: [] for m in ('V110', 'PL', 'M0')}
    identities = defaultdict(dict)
    multiple = set()
    with gzip.open(input_path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            p = np.asarray(row['probability'])
            odds = np.asarray(row['price'])
            hit = np.asarray(row['payout_per_100']) > 0
            target = np.asarray(row['target'])
            assert abs(p.sum()-1) < 1e-9 and np.array_equal(hit, target > 0)
            market = 1/odds
            market /= market.sum()
            order = np.argsort(-p, kind='stable')
            ranks = np.empty(len(p), dtype=int)
            ranks[order] = np.arange(1, len(p)+1)
            identities[row['race_id']][row['model']] = (row['keys'], hit.tolist())
            if hit.sum() > 1:
                multiple.add(row['race_id'])
            entries = [{'race_id': row['race_id'], 'date': row['race_date'], 'pair': row['keys'][i],
                        'p': float(p[i]), 'market_p': float(market[i]), 'hit': int(hit[i]),
                        'odds': float(odds[i]), 'rank': int(ranks[i])} for i in range(len(p))]
            top[row['model']].append(entries[int(order[0])])
            if row['model'] == 'V110':
                all_pairs.extend(entries)
                eligible = np.flatnonzero((odds >= 3)&(odds <= 100)&(p*odds >= 1.05))
                chosen = int(eligible[np.argmax((p*odds)[eligible])]) if len(eligible) else None
                assert chosen == row['chosen']
                if chosen is not None:
                    selected.append(entries[chosen])
    assert len(identities) == 1320
    assert all(set(v) == {'V110', 'PL', 'M0'} and v['V110'] == v['PL'] == v['M0'] for v in identities.values())
    assert len(selected) == 997 and sum(r['hit'] for r in selected) == 29
    for collection in (all_pairs, selected, *top.values()):
        b = bands(collection)
        assert sum(r['n'] for r in b) == len(collection)
        assert sum(r['hits'] for r in b) == sum(r['hit'] for r in collection)
    dates = sorted({r['date'] for r in top['V110']})
    draws = np.random.default_rng(335).integers(0, len(dates), (10000, len(dates)))
    population = {'all_pairs': all_pairs, 'top1': top['V110'], 'purchased': selected}
    result = {'source_sha256': digest, 'spec': '335', 'bootstrap_days': len(dates), 'bootstrap_draws': 10000,
              'bootstrap_seed': 335, 'multi_winning_pair_races': sorted(multiple),
              'populations': {k: {'all': summary(v), 'bands': bands(v),
                                 'years': {str(y): summary([r for r in v if r['date'].startswith(str(y))])
                                           for y in (2021, 2022, 2023)}} for k, v in population.items()},
              'top1_controls': {k: summary(v) for k, v in top.items()},
              'rank_all_pairs': {str(i): summary([r for r in all_pairs if r['rank'] == i]) for i in range(1, 6)},
              'rank_purchased': {str(i): summary([r for r in selected if r['rank'] == i]) for i in range(1, 6)},
              'calibration': {k: {prob: day_ci(v, dates, draws, prob) for prob in ('p', 'market_p')}
                              for k, v in population.items() if k != 'all_pairs'},
              'top1_minus_purchased': rate_difference(top['V110'], selected, dates, draws),
              'top1_minus_market_top1': rate_difference(top['V110'], top['M0'], dates, draws),
              'top1_matches_purchased': sum(r['rank'] == 1 for r in selected),
              'production_adoption': False, 'is_unseen_validation': False}
    for key, values in [('rank_all_pairs', all_pairs), ('rank_purchased', selected)]:
        result[key]['6+'] = summary([r for r in values if r['rank'] >= 6])
    assert sum(v['n'] for v in result['rank_all_pairs'].values()) == len(all_pairs)
    assert sum(v['hits'] for v in result['rank_all_pairs'].values()) == sum(r['hit'] for r in all_pairs)
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == digest
    output.mkdir(parents=True, exist_ok=False)
    for name, value in [('diagnosis.json', result), ('selection-ledger.json', {'top': top, 'purchased': selected}),
                        ('verification.json', {'status': 'passed', 'races': len(identities), 'input_sha256_unchanged': True,
                                               'purchased_bets': len(selected), 'purchased_hits': 29,
                                               'band_and_rank_totals': 'passed', 'multiple_winning_pair_races': len(multiple)})]:
        (output/name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps({k: v['all'] for k, v in result['populations'].items()}, ensure_ascii=False))
    print(json.dumps({'controls': result['top1_controls'], 'calibration': result['calibration'],
                      'top1_minus_market_top1': result['top1_minus_market_top1']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('artifacts/jra_research/v110_early_tokyo_20261023'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/jra_research/v110_probability_diagnostic_20261024'))
    args = parser.parse_args()
    run(args.source, args.output)
