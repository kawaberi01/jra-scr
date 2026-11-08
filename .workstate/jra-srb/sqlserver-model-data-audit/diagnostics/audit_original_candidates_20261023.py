"""概要: 東京V110・東京中山秋J23の保存版と推論入力契約を照合する。
作成日: 2026-10-23
入力: 既存モデル、元report/manifest、保存済み2026年入力。
出力: 指定した新規ディレクトリのaudit.jsonとreference-config.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/audit_original_candidates_20261023.py --output artifacts/jra_research/original_candidates_compatibility_20261023
注意事項: 既知SHAのモデルのみロードする。通信・DB・学習・実購入なし。技術再生は性能評価ではない。
"""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[4]
V110 = ROOT / '.workstate/jra-srb/jra-second-ten-nosummer-v1'
J23 = ROOT / 'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'


def sha(path):
    """ファイルのSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    """UTF-8のJSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def run(output):
    """元成果物を照合し、過去入力の結果遮断再生と参照構成を新規保存する。"""
    report = read(V110 / 'report.json')
    source_checks = {}
    for name, expected in report['source_hashes'].items():
        current, snapshot = ROOT / 'scripts' / name, V110 / 'source' / name
        assert sha(current) == sha(snapshot) == expected, name
        source_checks[str(current.relative_to(ROOT))] = expected
    model_path = V110 / report['final_artifact']['file']
    assert sha(model_path) == report['final_artifact']['sha256']
    cell = read(J23 / 'cells/2026-09_J23.json')
    jpath = J23 / 'cells' / cell['model_file']
    assert sha(jpath) == cell['model_sha256']
    manifest = read(J23 / 'manifest.json')
    for name in ['jra_research_chimera_thirty_model.py', 'jra_research_chimera_thirty_features.py']:
        relative = 'src/jra_srb/' + name
        assert sha(ROOT / relative) == manifest['code_sha256'][relative]
        source_checks[relative] = sha(ROOT / relative)

    sys.path.insert(0, str(ROOT / 'scripts'))
    from jra_second_ten_model import prepare, score_suite
    from jra_ten_trials_model import pick_ticket
    from jra_srb.jra_research_j23_live import load_frozen
    from jra_srb.jra_research_contracts import ResearchError

    suite = joblib.load(model_path)
    assert suite['training_max_date'] == report['final_artifact']['training_max_date'] < '2026-10-01'
    assert suite['training_races'] == report['final_artifact']['training_races']
    assert suite['fixed_policy'] == {'group': 'all', 'threshold': 1.05}
    assert not suite['candidate_gate_passed']['V110']
    frozen, parameters, provenance = load_frozen('2026-10-24')
    assert frozen['trained_through'] == cell['trained_through'] < '2026-10-01'
    november = None
    try:
        load_frozen('2026-11-01')
    except ResearchError as error:
        november = str(error)
    assert november and 'j23_missing_complete_prior_months' in november

    samples = []
    data = ROOT / 'data/training/jra_o1o2_asof_v1/2026/races.jsonl.gz'
    with gzip.open(data, 'rt', encoding='utf-8') as stream:
        for line in stream:
            race = json.loads(line)
            if int(race['race_date'][5:7]) in (6, 7, 8):
                continue
            clean = copy.deepcopy(race)
            clean.pop('result', None)
            clean['inputs']['odds'].pop('T-10m', None)
            with threadpool_limits(limits=1):
                original = score_suite(suite, prepare(race))['V110']
                prepared = prepare(clean)
                without_results = score_suite(suite, prepared)['V110']
            assert np.array_equal(original['probability'], without_results['probability'])
            assert np.array_equal(original['projected_return'], without_results['projected_return'])
            assert np.isfinite(original['probability']).all()
            assert abs(float(original['probability'].sum()) - 1) < 1e-9
            samples.append({'race_id': race['race_id'], 'race_date': race['race_date'],
                            'pair_count': len(prepared['pair']['keys']),
                            'probability_max_difference': 0.0,
                            'ticket_unchanged': pick_ticket(prepared['pair'], original, 'quinella', suite['fixed_policy']) ==
                            pick_ticket(prepared['pair'], without_results, 'quinella', suite['fixed_policy'])})
            if len(samples) == 3:
                break
    assert len(samples) == 3 and all(row['ticket_unchanged'] for row in samples)
    jlive = ROOT / 'src/jra_srb/jra_research_j23_live.py'
    source_checks[str(jlive.relative_to(ROOT))] = sha(jlive)
    reference = {
        'status': 'research_reference_only', 'adopted': False,
        'selection_uses_previously_seen_results': True,
        'veto_enabled': False, 'combined_ticket_policy': None,
        'V110': {'model': str(model_path.relative_to(ROOT)), 'model_sha256': sha(model_path),
                 'trial_argument_required': 'V110', 'default_trial': suite['development_champion'],
                 'training_max_date': suite['training_max_date'], 'training_races': suite['training_races'],
                 'scope': {'course': '東京', 'course_code': '05', 'excluded_months': suite['excluded_months']},
                 'policy': {'bet_type': 'quinella', 'odds_inclusive': [3, 100], 'ev_min': 1.05,
                            'probability_min': None, 'max_tickets': 1, 'group': 'all',
                            'comparison_stake_yen': 600, 'original_stake_yen': 100},
                 'features': suite['enriched_feature_names'], 'candidate_gate_passed': False},
        'J23': {'model': str(jpath.relative_to(ROOT)), 'model_sha256': sha(jpath),
                'training_max_date': frozen['trained_through'], 'training_races': cell['train_races'],
                'scope': {'courses': ['東京', '中山'], 'course_codes': ['05', '06'], 'months': [9, 10, 11]},
                'policy': {'bet_type': 'quinella', 'odds_inclusive': [4, 80], 'ev_min': 1.05,
                           'probability_min': .015, 'max_tickets': 1, 'comparison_stake_yen': 600,
                           'Q03_enabled': False, 'Q06_enabled': False},
                'horse_features': 12, 'pair_features': 28,
                'original_model_updates': 'monthly_refit', 'reference_model_updates': 'none'},
        'scope_enforced_by_current_entry_points': False,
        'performance_eligible': False, 'source_sha256': source_checks,
    }
    audit = {'status': 'passed_with_known_gaps', 'source_hashes_match': True,
             'model_hashes_match': True, 'technical_replay': samples,
             'technical_replay_is_performance_test': False,
             'J23_october_initialization': provenance,
             'J23_Q03_Q06_coefficients_through': parameters['trained_through_month'],
             'J23_november_entry_refusal': november,
             'gaps': ['V110 default is V105; require explicit --trial V110',
                      'Current entry points do not enforce the reference geographic/seasonal scope',
                      'V110 requires enriched historical feature JSON and complete T-30m O1/O2, not raw API JSON',
                      'V110 checks announcement cutoff but does not prove receipt-before-cutoff or all history provenance',
                      'J23 original-only November inference is coupled to Q03/Q06 complete monthly coefficient history',
                      'Latest frozen models differ from rolling historical fold models; future performance unverified',
                      'J23 live inputs remain runtime_validation_only due to publication/receipt evidence gaps'],
             'new_fits': 0, 'sql_calls': 0, 'http_calls': 0, 'adopted': False}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in [('reference-config.json', reference), ('audit.json', audit)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': audit['status'], 'replays': len(samples),
                      'V110_training_through': suite['training_max_date'],
                      'J23_training_through': frozen['trained_through'], 'adopted': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
