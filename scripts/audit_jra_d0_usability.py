"""概要: D0/BC/市場の固定馬連1点を元公式払戻と照合し、実用採否を判定する。
作成日: 2026-10-25
入力: spec410/415、D0保存分布/元カード、BC保存分布、当日scout。
出力: 新runの全精算行/回収率/条件別集計/入力監査/現在採否/前向き計画。
実行例: uv run --frozen --extra ml python scripts/audit_jra_d0_usability.py --output artifacts/jra_research/d0_usability_20261025
注意事項: SQL/HTTP/新学習/既定変更/購入なし。未来実績の代用にしない。
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_course_chimera as shared
from jra_srb import jra_research_d0_usability as model

ROOT, REFERENCE = shared.ROOT, shared.REFERENCE
read, save, sha, require = shared.read, shared.save, shared.sha, shared.require
BC = ROOT/'artifacts/jra_research/class_D0_20261025'
SCOUT = ROOT/'artifacts/predictions/20261025-day-confidence-summary/scout-final.json'
SPECS = [ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec'/name for name in
    ('410-D0実用可否の収益と入力監査.md', '415-D0とBCの前向き固定比較.md')]


def verify_payouts(records):
    """評価の正解ペアと100円公式払戻を元カード結果から直接再照合する。"""
    wanted, seen = {r['race_id']: r for r in records}, set()
    hashes = read(REFERENCE/'dataset-manifest.json')['card_sha256']
    used, verified = {}, {}
    for relative, digest in hashes.items():
        path = ROOT/relative
        if path.parent.name not in ('2024', '2025', '2026'):
            continue
        require(sha(path) == digest, 'usability_source_card_sha')
        used[relative] = digest
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                source = json.loads(line)
                key = source['race_id']
                if key not in wanted:
                    continue
                r, outcome = wanted[key], source['result']
                pairs = list(combinations(r['horses'], 2))
                target = tuple(int(h) for h in pairs[r['winner']])
                payouts = outcome['quinella_payout_per_100_yen']
                require(key not in seen and len(payouts) == 1 and not outcome['rank_payout_exception']
                    and not outcome['settlement']['nonformed'] and not outcome['settlement']['special_pay'], 'usability_outcome_contract')
                payout = payouts[0]
                pair = tuple(sorted((int(payout['horse_no_1']), int(payout['horse_no_2']))))
                ranks = {int(h): int(v) for h, v in outcome['ranks_by_horse'].items() if v is not None}
                official = int(payout['payout'])
                require(pair == target and {ranks[h] for h in pair} == {1, 2} and official > 0
                    and ('payout_yen' not in r or r['payout_yen'] == official), 'usability_payout_or_target_mismatch')
                verified[key] = {'winner_pair': list(pair), 'payout_per_100_yen': official,
                    'source_dataset_payout_present': 'payout_yen' in r}
                seen.add(key)
    require(seen == set(wanted), 'usability_missing_outcomes')
    return used, verified


def ticket_rows(test, probabilities, label):
    """結果を参照せず選んだ確率1位を、評価時だけ正解と公式円で精算する。"""
    rows = []
    for r, p in zip(test, probabilities, strict=True):
        chosen = int(np.argmax(p))
        hit = int(chosen == r['winner'])
        rows.append({'race_id': r['race_id'], 'race_date': r['race_date'], 'course': int(r['course']),
            'surface': int(r['surface']), 'distance_band': shared.model.base.core.base.distance_band(r['distance']),
            'label': label, 'pair_index': chosen, 'top_probability': float(p[chosen]), 'hit': hit,
            'payout_yen': int(r['payout_yen']) if hit else 0})
    return rows


def groups(rows):
    """年別・全10場・芝ダート距離別を全件集計し、良好群の選別をしない。"""
    out = defaultdict(list)
    for r in rows:
        for key in ('year:'+r['race_date'][:4], 'course:'+str(r['course']),
            'sd:'+str(r['surface'])+':'+str(r['distance_band'])):
            out[key].append(r)
    return {k: model.summary(v) for k, v in sorted(out.items())}


def input_audit(folder):
    """当日全日保存から分析可否と全場履歴証拠を確認し、厳格適格への昇格を拒否する。"""
    scout = read(SCOUT)
    counts = Counter(r['status'] for r in scout['entries'])
    reasons = Counter(r.get('reason') for r in scout['entries'] if r['status'] != 'analyzed')
    require(len(scout['entries']) == scout['inventory_count'] and counts['analyzed'] == scout['analyzed_count'], 'usability_scout_counts')
    details, hashes = [], {str(SCOUT.relative_to(ROOT)): sha(SCOUT)}
    for entry in scout['entries']:
        if entry['status'] != 'analyzed':
            continue
        snapshot = Path(entry['snapshot_dir'])
        paths = [snapshot/'input/quality.json', snapshot/'input/input.json', snapshot/'official-card.json', snapshot/'official-odds.json']
        available = all(p.exists() for p in paths)
        detail = {'race_id': entry['race_id'], 'reference_analyzed': True, 'strict_prospective_eligible': False,
            'strict_rejection_reasons': ['all_course_history_not_verified', 'outside_fixed_T30_capture', 'predeadline_independent_evidence_not_verified']}
        if available:
            for p in paths:
                hashes[str(p.relative_to(ROOT))] = sha(p)
            quality, public, card, odds = map(read, paths)
            detail.update({'quality_status': quality['status'], 'historical_publication_verified': quality.get('historical_publication_verified', False),
                'card_sha_matches_quality': sha(paths[2]) == quality['card_sha256'],
                'history_latest_raw_days': {k: v['latest_raw_day'] for k, v in quality['additional_coverage'].items()},
                'all_course_history_latest_verified': entry['input_state']['history']['all_course_latest_verified'],
                'near_post_latest_verified': entry['input_state']['near_post_latest_verified'],
                'public_runners': len(public['horses']), 'card_observed_at': card['fetched_at'], 'odds_observed_at': odds['fetched_at']})
            require(detail['all_course_history_latest_verified'] is False and detail['near_post_latest_verified'] is False,
                'usability_scout_changed_requires_new_protocol')
        else:
            detail['strict_rejection_reasons'].append('snapshot_files_missing')
        details.append(detail)
    audit = {'inventory': len(scout['entries']), 'reference_analyzed': counts['analyzed'], 'status_counts': dict(counts),
        'unavailable_reason_counts': dict(reasons), 'strict_eligible': 0, 'entries': details,
        'all_day_use_ready': False, 'source_sha256': hashes}
    save(folder/'input-audit.json', audit)
    return audit


def run(folder):
    """固定ベンチマークを精算し、現在の参考利用と購入不採用の根拠を保存する。"""
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        initial = {**shared.sources(), **{str(p.relative_to(ROOT)): sha(p) for p in (*SPECS, Path(__file__), Path(model.__file__))}}
        fixed_at = datetime.now(timezone.utc)
        save(folder/'protocol.json', {'source_sha256': initial, 'fixed_at': fixed_at.isoformat(),
            'ticket': 'all_races_top1_quinella_100yen', 'unknown_test': False, 'no_posthoc_filter': True})
        records, later, baseline = shared.load_inputs(folder)
        test = [r for r in records if r['race_date'] >= '2024-01-01']+later
        require(read(BC/'independent-verification.json')['status'] == 'passed', 'usability_BC_unverified')
        bc_manifest = read(BC/'manifest.json')
        probabilities, bc_hashes = {}, {}
        by_id = {r['race_id']: r for r in test}
        for year in (2024, 2025, 2026):
            cell = read(BC/f'{year}_BC.json')
            require(sha(BC/f'{year}_BC.joblib') == bc_manifest['model_sha256'][f'{year}_BC.joblib'], 'usability_BC_model_sha')
            pp = BC/f'{year}_BC_predictions.joblib'
            bc_hashes[str(pp.relative_to(ROOT))] = sha(pp)
            for key, p, row in zip(cell['test_ids'], joblib.load(pp), cell['rows']['BC'], strict=True):
                r = by_id[key]
                require(abs(-np.log(p[r['winner']])-row['loss']) < 1e-12
                    and int(np.argmax(p) == r['winner']) == row['hit'], 'usability_BC_saved_value')
                probabilities[key] = p
        require(set(probabilities) == {r['race_id'] for r in test}, 'usability_BC_roster')
        stage = 'official_payouts'
        card_hashes, outcomes = verify_payouts(test)
        save(folder/'official-outcomes.json', outcomes)
        test = [{**r, 'payout_yen': outcomes[r['race_id']]['payout_per_100_yen']} for r in test]
        rows = {'D0': ticket_rows(test, [baseline[r['race_id']] for r in test], 'D0'),
            'BC': ticket_rows(test, [probabilities[r['race_id']] for r in test], 'BC'),
            'market': ticket_rows(test, [r['market'] for r in test], 'market')}
        summaries = {k: {'all': model.summary(v), 'roi_ci': model.roi_ci(v), 'groups': groups(v)} for k, v in rows.items()}
        save(folder/'tickets.json', rows)
        save(folder/'returns.json', summaries)
        stage = 'input_readiness'
        audit = input_audit(folder)
        d0 = summaries['D0']
        evidence = {'prospective_sample_sufficient': False, 'predictions_and_rule_fixed_before_results': False,
            'asof_and_history_verified': False, 'roi_ci_lower_above_one': d0['roi_ci']['roi_ci95'][0] > 1,
            'annual_profit_robust': all(v['net_yen'] > 0 for k, v in d0['groups'].items() if k.startswith('year:')),
            'not_single_hit_dependent': d0['all']['net_without_largest_hit_yen'] > 0}
        decision = model.purchase_decision(evidence)
        save(folder/'decision.json', {**decision, 'research_reference_allowed': True,
            'research_scope': 'individual_races_with_verified_inputs_only; historical_asof_unverified',
            'all_day_use_ready': audit['all_day_use_ready'], 'prospective_eligible_races': 0,
            'top1_policy_only_not_all_possible_betting_strategies': True,
            'unknown_test': False, 'default_model_changed': False})
        save(folder/'prospective-protocol.json', {'fixed_at': fixed_at.isoformat(),
            'end_at': (fixed_at+timedelta(days=180)).isoformat(), 'minimum_races': 1000, 'minimum_days': 40,
            'primary': 'D0_vs_market_logloss', 'secondary': 'BC_vs_D0', 'stake_yen': 100,
            'model_sha256': {'D0': sha(REFERENCE/'final_model.joblib'), 'BC': sha(BC/'2026_BC.joblib')},
            'performance_trial_started': False, 'accepted': 0, 'input_rejections_logged': len(audit['entries']),
            'reason': 'current history coverage and T30/predeadline evidence not verified', 'spec': str(SPECS[1].relative_to(ROOT))})
        require(all(sha(ROOT/p) == h for p, h in {**initial, **card_hashes, **bc_hashes, **audit['source_sha256']}.items()), 'usability_source_changed')
        save(folder/'manifest.json', {'status': 'complete', 'source_sha256': initial, 'card_sha256': card_hashes,
            'bc_predictions_sha256': bc_hashes, 'outputs_sha256': {p.name: sha(p) for p in folder.glob('*.json')},
            'evaluated_races': len(test), 'new_fits': 0})
        print(json.dumps({'decision': decision, 'summaries': {k: v['all'] for k, v in summaries.items()}}, ensure_ascii=False))
    except Exception as error:
        save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
