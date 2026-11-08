"""概要: 保存D0と市場の同一競走比較を、競馬場/距離/季節の交差条件で記述する。
作成日: 2026-10-24
入力: spec375、独立検算済みD0成功runの競走別評価とdataset。
出力: 新規dirの全条件集計と件数・全体一致証跡。
実行例: uv run --frozen --extra ml python scripts/diagnose_jra_d0_conditions.py --output artifacts/jra_research/d0_condition_diagnostic_20261024
注意事項: 学習/SQL/HTTP/予想変更なし。多重比較の記述であり採用条件にはしない。
"""

import argparse
from collections import defaultdict
import math
from pathlib import Path

import joblib
import numpy as np

import run_jra_quality_chimera as runner


def aggregate(rows):
    """同一競走の損失差と的中数を合算し、3年の内訳を保持する。"""
    out = {'races': len(rows), 'D0_loss': float(np.mean([r['loss'] for r in rows])),
        'market_loss': float(np.mean([r['market_loss'] for r in rows])),
        'D0_hits': sum(r['hit'] for r in rows), 'market_hits': sum(r['market_hit'] for r in rows)}
    out['loss_improvement'] = out['market_loss']-out['D0_loss']
    return out


def diagnose(folder):
    """全対応IDを照合して3段階の交差条件を集計し、全体一致を確認する。"""
    folder.mkdir(parents=True, exist_ok=False)
    read, sha, require = runner.read, runner.sha, runner.require
    source = runner.REFERENCE
    manifest = read(source/'model-manifest.json')
    require(read(source/'independent-verification.json')['status'] == 'passed'
            and sha(source/'dataset.joblib') == manifest['dataset_sha256']
            and sha(source/'assessment.json') == manifest['assessment_sha256']
            and sha(source/'final_model.joblib') == manifest['model_sha256']
            and all(sha(runner.ROOT/p) == value for p, value in manifest['source_sha256'].items()), 'diagnostic_source_unverified')
    data = joblib.load(source/'dataset.joblib')
    inputs = {r['race_id']: r for r in data['records']+data['later']}
    files = [source/'2024_D0.json', source/'2025_D0.json', source/'2026_selected.json']
    for year in (2024, 2025):
        require(sha(source/f'{year}_D0.joblib') == read(source/f'{year}_D0.json')['model_sha256'], 'diagnostic_annual_model_sha')
    rows = [r for p in files for r in read(p)['rows']]
    require(len({r['race_id'] for r in rows}) == len(rows) == 7857, 'diagnostic_ids')
    expected = read(source/'assessment.json')['pooled_selected']
    require(runner.helper.summary(rows) == expected, 'diagnostic_D0_summary')
    for row in rows:
        r = inputs[row['race_id']]
        require(row['race_date'] == r['race_date'] and row['race_date'][:4] in ('2024', '2025', '2026'), 'diagnostic_date')
        row['market_loss'] = -math.log(r['market'][r['winner']])
        row['market_hit'] = int(np.argmax(r['market']) == r['winner'])
    output = {'scope': 'exploratory_description_no_model_or_betting_selection', 'all': aggregate(rows), 'groups': {}}
    for level, keys in [('cs', ('course', 'surface')), ('csd', ('course', 'surface', 'distance_band')),
                        ('csds', ('course', 'surface', 'distance_band', 'season'))]:
        groups = defaultdict(list)
        for row in rows:
            groups[tuple(row[k] for k in keys)].append(row)
        values = []
        for key, values_in_group in sorted(groups.items()):
            years = {year: aggregate([r for r in values_in_group if r['race_date'].startswith(year)])
                     for year in ('2024', '2025', '2026') if any(r['race_date'].startswith(year) for r in values_in_group)}
            require(sum(v['races'] for v in years.values()) == len(values_in_group), 'diagnostic_year_partition')
            values.append({'condition': dict(zip(keys, key, strict=True)), **aggregate(values_in_group), 'years': years,
                'descriptive_sample_available': len(values_in_group) >= 100 and len(years) == 3 and all(v['races'] >= 20 for v in years.values()),
                'market_loss_better_all_three_years': len(years) == 3 and all(v['loss_improvement'] > 0 for v in years.values())})
        require(sum(v['races'] for v in values) == len(rows), 'diagnostic_group_count')
        output['groups'][level] = values
    long = [r for r in rows if r['course'] == 8 and r['surface'] == 0 and r['distance_band'] == 4]
    output['kyoto_turf_2601m_plus'] = aggregate(long) if long else {'races': 0}
    output['source_sha256'] = {str(p.relative_to(runner.ROOT)): sha(p) for p in files+[source/'dataset.joblib', source/'assessment.json', Path(__file__),
        runner.ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/375-D0の競走条件別診断.md']}
    runner.save(folder/'conditions.json', output)
    runner.save(folder/'verification.json', {'status': 'passed', 'race_ids': len(rows), 'all_summary_equal': True,
        'three_partition_counts_equal': True, 'fits': 0, 'prediction_changes': 0, 'unknown_test': False})
    for level, values in output['groups'].items():
        eligible = [v for v in values if v['descriptive_sample_available']]
        best = sorted(eligible, key=lambda v: v['loss_improvement'], reverse=True)
        print({'level': level, 'groups': len(values), 'descriptive_sample_groups': len(eligible),
            'positive_pooled': sum(v['loss_improvement'] > 0 for v in eligible),
            'positive_all_years': sum(v['market_loss_better_all_three_years'] for v in eligible),
            'best': [{k: v[k] for k in ('condition', 'races', 'loss_improvement')} for v in best[:3]],
            'worst': [{k: v[k] for k in ('condition', 'races', 'loss_improvement')} for v in best[-3:]]})
    print({'kyoto_turf_2601m_plus': output['kyoto_turf_2601m_plus']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    diagnose(parser.parse_args().output)
