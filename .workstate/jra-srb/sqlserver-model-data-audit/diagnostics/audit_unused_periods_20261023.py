"""概要: 保存データと評価履歴の競走IDを照合し、未評価と未使用を区別する。
作成日: 2026-10-23
入力: 元J23セル、V110予測、関連保存予測、2026年v1/v2データと既存監査。
出力: 新規ディレクトリのinventory.json、eligibility.json、verification.json。
実行例: uv run --frozen python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/audit_unused_periods_20261023.py --output artifacts/jra_research/unused_period_audit_20261023
注意事項: 日付・ID・件数・来歴のみ集計。結果/確率/払戻を評価せず、SQL/HTTP/学習なし。未照合を未使用と断定しない。
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
V110 = ROOT / '.workstate/jra-srb/jra-second-ten-nosummer-v1'


def read(path):
    """UTF-8 JSONを読む。数値成績の出力や再計算は行わない。"""
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """証跡として入力ファイルSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_rows(path, trial=None):
    """JSONLから日付と12桁競走IDだけを抽出し、空ファイルと不明IDを区別する。"""
    races, lines, unmatched = {}, 0, 0
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            lines += 1
            value = json.loads(line)
            if trial and value.get('trial') != trial:
                continue
            key = value.get('race_id', value.get('race_key'))
            if not isinstance(key, str) or not re.fullmatch(r'[0-9]{12}', key):
                unmatched += 1
                continue
            day = key[:4] + '-' + key[4:6] + '-' + key[6:8]
            assert value.get('race_date', day) == day
            races[key] = day
    return races, {'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'lines': lines,
                   'unique_races': len(races), 'unmatched_id_lines': unmatched,
                   'min_date': min(races.values(), default=None),
                   'max_date': max(races.values(), default=None)}


def run(output):
    """候補別の時間条件と既参照競走を照合し、独立未使用を証明できるか記録する。"""
    config_path = ROOT / 'artifacts/jra_research/original_candidates_compatibility_20261023/reference-config.json'
    config = read(config_path)
    j23, cells = {}, []
    for path in sorted((SOURCE / 'cells').glob('*_J23.json')):
        value = read(path)
        assert value['case'] == 'J23' and value['status'] == 'evaluated'
        for row in value['rows']:
            j23[row['race_key']] = row['race_date']
        cells.append({'path': str(path.relative_to(ROOT)), 'month': value['month'],
                      'rows': len(value['rows']), 'sha256': sha(path)})
    assert len(cells) == 30 and len(j23) == 7127
    v110, vmeta = index_rows(V110 / 'predictions.jsonl.gz', trial='V110')
    related, metadata = set(j23) | set(v110), []
    paths = sorted((ROOT / 'artifacts/jra_research/runs').glob('*/predictions.jsonl.gz'))
    paths += sorted((ROOT / '.workstate/jra-srb').glob('jra-*/predictions.jsonl.gz'))
    for path in paths:
        races, meta = index_rows(path)
        related.update(races)
        metadata.append(meta)
    data_paths = [ROOT / 'data/training/jra_o1o2_asof_v1/2026/races.jsonl.gz',
                  ROOT / 'data/training/jra_o1o2_asof_v2/20261002-raw-v2-complete/2026/races.jsonl.gz']
    datasets, union = [], {}
    for path in data_paths:
        races, meta = index_rows(path)
        manifest = read(path.parent / 'manifest.json')
        assert manifest['files']['races.jsonl.gz']['sha256'] == meta['sha256']
        meta['monthly_counts'] = dict(sorted(Counter(day[:7] for day in races.values()).items()))
        datasets.append(meta)
        union.update(races)
    eligibility = {}
    for name, evaluated in [('J23', j23), ('V110', v110)]:
        cutoff = config[name]['training_max_date']
        eligible = {key for key, day in union.items() if day > cutoff and
                    (key[8:10] in ('05', '06') and int(day[5:7]) in (9, 10, 11) if name == 'J23'
                     else key[8:10] == '05' and int(day[5:7]) not in (6, 7, 8))}
        directly_used = eligible & set(evaluated)
        other_used = (eligible - directly_used) & related
        unknown = eligible - related
        assert directly_used | other_used | unknown == eligible
        assert not directly_used & other_used and not directly_used & unknown and not other_used & unknown
        eligibility[name] = {'frozen_model_training_through': cutoff,
                             'saved_evaluation_min': min(evaluated.values()),
                             'saved_evaluation_max': max(evaluated.values()),
                             'scope_and_after_training_races': len(eligible),
                             'direct_candidate_evaluation_overlap': len(directly_used),
                             'other_research_prediction_overlap': len(other_used),
                             'not_found_in_scanned_prediction_files': len(unknown),
                             'unknown_race_ids': sorted(unknown),
                             'unknown_is_not_proven_unseen': True,
                             'verified_independent_holdout_races': 0}
    frozen = read(SOURCE / 'frozen.json')
    assert frozen['config']['retrospective_previously_seen_data'] is True
    readiness_path = ROOT / 'artifacts/jra_research/j23_october_trial_20261023/readiness.json'
    readiness = read(readiness_path)
    assert readiness['october_receipts']['card_odds_result_intersection'] == 0
    inventory = {'J23_cells': cells, 'J23_evaluated_races': len(j23),
                 'V110_predictions': vmeta, 'related_prediction_files': metadata,
                 'data_files': datasets, 'data_union_races': len(union),
                 'october_or_later_saved_dataset_races': sum(day >= '2026-10-01' for day in union.values()),
                 'source_config_sha256': sha(config_path), 'frozen_sha256': sha(SOURCE / 'frozen.json'),
                 'october_metadata_evidence': {'path': str(readiness_path.relative_to(ROOT)),
                    'sha256': sha(readiness_path), 'checked_at_utc': readiness['checked_at_utc'],
                    'card_odds_result_intersection': 0, 'new_sql_check': False}}
    decision = {'status': 'no_verified_ready_independent_holdout_identified',
                'candidates': eligibility,
                'periods': {'through_2026_09': 'previously_referenced_or_not_proven_unseen',
                            '2026_10_01_to_2026_10_23': 'unseen_status_unproven_and_no_ready_complete_bundle_identified',
                            'future_after_protocol_lock': 'eligible_for_prospective_validation_if_pre_race_evidence_is_preserved'},
                'scope_limit': 'local candidate datasets/predictions and existing SQL audit evidence; not every database, human memory or external session',
                'new_performance_calculations': 0, 'new_fits': 0, 'sql_calls': 0, 'http_calls': 0,
                'adopted': False}
    output.mkdir(parents=True, exist_ok=False)
    for filename, value in [('inventory.json', inventory), ('eligibility.json', decision),
                             ('verification.json', {'status': 'passed', 'J23_cells': 30,
                              'J23_races': 7127, 'dataset_hashes_match': True,
                              'partitions_disjoint': True, 'no_outcome_fields_used_in_calculation': True})]:
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': decision['status'], 'candidates': {
                      name: {k: v for k, v in value.items() if k != 'unknown_race_ids'}
                      for name, value in eligibility.items()},
                      'dataset_ranges': [{k: d[k] for k in ('path', 'unique_races', 'min_date', 'max_date')} for d in datasets],
                      'empty_prediction_files': sum(d['lines'] == 0 for d in metadata)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
