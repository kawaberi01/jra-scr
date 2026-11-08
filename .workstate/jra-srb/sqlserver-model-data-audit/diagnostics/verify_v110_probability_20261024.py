"""概要: V110確率診断を元保存行から別集計し、同一購入競走の比較を補足する。
作成日: 2026-10-24
入力: 固定パスの旧年代予測とv110_probability_diagnostic_20261024。
出力: independent-verification.json、same-race-comparison.json。正常0、不一致は例外停止。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/verify_v110_probability_20261024.py
注意事項: 再学習・外部通信なし。新規補足ファイルのみ保存し既存結果は上書きしない。
"""

import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def main():
    """独立した逐次集計で帯・順位・年別を確認し、同じ997競走を比較する。"""
    folder = Path('artifacts/jra_research/v110_probability_diagnostic_20261024')
    path = Path('artifacts/jra_research/v110_early_tokyo_20261023/predictions.jsonl.gz')
    result = json.loads((folder/'diagnosis.json').read_text('utf-8'))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == result['source_sha256']
    source_rows = []
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row['model'] == 'V110':
                source_rows.append(row)
    pairs, first, purchased = [], [], []
    first_by_id = {}
    for row in source_rows:
        sorted_indices = sorted(range(row['pair_count']), key=lambda i: -row['probability'][i])
        for rank, i in enumerate(sorted_indices, 1):
            item = {'p': row['probability'][i], 'hit': int(row['payout_per_100'][i] > 0),
                    'rank': rank, 'date': row['race_date']}
            pairs.append(item)
            if rank == 1:
                first.append(item)
                first_by_id[row['race_id']] = item
            if row['chosen'] == i:
                purchased.append({**item, 'race_id': row['race_id']})
    checks = 0
    for name, values in [('all_pairs', pairs), ('top1', first), ('purchased', purchased)]:
        groups = [(result['populations'][name]['all'], values)]
        groups += [(b, [v for v in values if b['lower_inclusive'] <= v['p'] < b['upper_exclusive']])
                   for b in result['populations'][name]['bands']]
        groups += [(b, [v for v in values if v['date'].startswith(y)])
                   for y, b in result['populations'][name]['years'].items()]
        for actual, rows in groups:
            assert actual['n'] == len(rows) and actual['hits'] == sum(v['hit'] for v in rows)
            if rows:
                assert math.isclose(actual['expected_hits'], math.fsum(v['p'] for v in rows), abs_tol=1e-10)
            checks += 1
    for name, values in [('rank_all_pairs', pairs), ('rank_purchased', purchased)]:
        for key, actual in result[name].items():
            rows = [v for v in values if (v['rank'] >= 6 if key == '6+' else v['rank'] == int(key))]
            assert actual['n'] == len(rows) and actual['hits'] == sum(v['hit'] for v in rows)
            checks += 1
    same_first = [first_by_id[v['race_id']] for v in purchased]
    assert len(same_first) == len(purchased) == 997
    dates = sorted({v['date'] for v in purchased})
    first_hits = np.array([sum(v['hit'] for v in same_first if v['date'] == d) for d in dates])
    bought_hits = np.array([sum(v['hit'] for v in purchased if v['date'] == d) for d in dates])
    counts = np.array([sum(v['date'] == d for v in purchased) for d in dates])
    draws = np.random.default_rng(335).integers(0, len(dates), (10000, len(dates)))
    deltas = (first_hits-bought_hits)[draws].sum(axis=1)/counts[draws].sum(axis=1)
    comparison = {'scope': 'Same 997 races where original policy purchased', 'n': 997,
                  'top1_hits': sum(v['hit'] for v in same_first), 'purchased_hits': 29,
                  'top1_hit_rate': sum(v['hit'] for v in same_first)/997,
                  'purchased_hit_rate': 29/997,
                  'difference': (sum(v['hit'] for v in same_first)-29)/997,
                  'day_bootstrap_ci95_difference': np.quantile(deltas, [.025, .975]).tolist(),
                  'top1_only_diagnostic_not_new_betting_policy': True,
                  'purchased_probability_below_5pct': sum(v['p'] < .05 for v in purchased),
                  'years': {str(y): {'n': sum(v['date'].startswith(str(y)) for v in same_first),
                                     'top1_hits': sum(v['hit'] for v in same_first if v['date'].startswith(str(y)))}
                            for y in (2021, 2022, 2023)}}
    verification = {'status': 'passed', 'independent_summary_checks': checks,
                    'races': len(source_rows), 'pairs': len(pairs), 'purchased': len(purchased),
                    'hits': sum(v['hit'] for v in purchased), 'source_sha256_unchanged': True}
    for name, data in [('same-race-comparison.json', comparison), ('independent-verification.json', verification)]:
        with (folder/name).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'verification': verification, 'same_race_comparison': comparison}, ensure_ascii=False))


if __name__ == '__main__':
    main()
