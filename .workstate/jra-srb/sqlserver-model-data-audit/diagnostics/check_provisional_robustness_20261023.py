"""概要: 仮採用候補の固定範囲について年・購入日を外した収支頑健性を診断する。
作成日: 2026-10-23
入力: 067で元会計を照合済みのledger.json。結果は既使用の探索データ。
出力: 新規dirの事前診断規則、仮採用記録、頑健性結果、検算JSON。
実行例: uv run --frozen python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/check_provisional_robustness_20261023.py --output artifacts/jra_research/provisional_robustness_20261023
注意事項: 新政策・学習・SQL・HTTP・実購入なし。分割を独立未知検証とは呼ばない。
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LEDGER = ROOT / 'artifacts/jra_research/tokyo_nakayama_reanalysis_20261023/ledger.json'
REFERENCE = ROOT / 'artifacts/jra_research/original_candidates_compatibility_20261023/reference-config.json'


def save(path, value):
    """新規JSONを実バイトUTF-8/LFで排他保存する。"""
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def summarize(rows, model):
    """固定元政策の会計と全競走精度を集計し、条件は変えない。"""
    stake = sum(r['models'][model]['stake'] for r in rows)
    payout = sum(r['models'][model]['payout'] for r in rows)
    buys = [r for r in rows if r['models'][model]['stake']]
    return {'races': len(rows), 'bets': len(buys), 'buy_days': len({r['race_date'] for r in buys}),
            'hits': sum(r['models'][model]['payout'] > 0 for r in buys),
            'stake_yen': stake, 'payout_yen': payout, 'profit_yen': payout-stake,
            'roi': payout/stake if stake else None,
            'model_logloss': sum(r['models'][model]['loss'] for r in rows)/len(rows) if rows else None,
            'M0_logloss': sum(r['models']['M0']['loss'] for r in rows)/len(rows) if rows else None}


def diagnose(rows, model):
    """事前固定した年/購入日除外と時系列二分だけを診断する。"""
    rows = sorted(rows, key=lambda r: (r['race_date'], r['race_key']))
    total = summarize(rows, model)
    years = sorted({r['race_date'][:4] for r in rows})
    days = sorted({r['race_date'] for r in rows if r['models'][model]['stake']})
    day_stats = {day: summarize([r for r in rows if r['race_date'] == day], model) for day in days}
    omit_day = {day: {'bets': total['bets']-s['bets'],
                     'profit_yen': total['profit_yen']-s['profit_yen'],
                     'roi': (total['payout_yen']-s['payout_yen'])/(total['stake_yen']-s['stake_yen'])}
                for day, s in day_stats.items()}
    half = len(days)//2
    before_days = set(days[:half])
    after_days = set(days[half:])
    before = summarize([r for r in rows if r['race_date'] in before_days], model)
    after = summarize([r for r in rows if r['race_date'] in after_days], model)
    assert before['stake_yen']+after['stake_yen'] == total['stake_yen']
    assert before['payout_yen']+after['payout_yen'] == total['payout_yen']
    leave_year = {year: summarize([r for r in rows if r['race_date'][:4] != year], model) for year in years}
    verification = []
    for day, result in omit_day.items():
        independent = summarize([r for r in rows if r['race_date'] != day], model)
        assert independent['roi'] == result['roi'] and independent['profit_yen'] == result['profit_yen']
        verification.append(day)
    return {'total': total, 'years': {y: summarize([r for r in rows if r['race_date'][:4] == y], model) for y in years},
            'venues': {v: summarize([r for r in rows if r['course'] == v], model) for v in sorted({r['course'] for r in rows})},
            'chronological_buy_day_halves': {'split_rule': 'first floor(N/2) purchase days vs remaining purchase days',
                'first_last_day': days[half-1], 'second_first_day': days[half], 'first': before, 'second': after,
                'accuracy_scope': 'purchase days only in halves; total accuracy is on all scoped races'},
            'leave_one_year_out': leave_year,
            'purchase_day_summary': {'positive_days': sum(s['profit_yen'] > 0 for s in day_stats.values()),
                                     'negative_days': sum(s['profit_yen'] < 0 for s in day_stats.values()),
                                     'zero_days': sum(s['profit_yen'] == 0 for s in day_stats.values())},
            'leave_one_buy_day_out': {'checked_days': len(days),
                'positive_profit_cases': sum(v['profit_yen'] > 0 for v in omit_day.values()),
                'worst': min(omit_day.items(), key=lambda item: item[1]['roi']),
                'best': max(omit_day.items(), key=lambda item: item[1]['roi']), 'all': omit_day},
            'independent_day_omission_checks': len(verification), 'is_unseen_validation': False}


def run(output):
    """仮採用と診断規則を先に保存し、既知対象の頑健性と検算を記録する。"""
    source_sha = hashlib.sha256(LEDGER.read_bytes()).hexdigest()
    reference = json.loads(REFERENCE.read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    save(output/'protocol.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'ledger_sha256': source_sha, 'primary': 'J23_tokyo_nakayama_autumn', 'comparison': 'V110_tokyo',
        'diagnostics': ['annual', 'venue', 'leave_one_year_out', 'leave_one_purchase_day_out',
                        'chronological_half_by_purchase_days'],
        'policy_changes': 0, 'new_fits': 0, 'independent_unseen_validation': False})
    save(output/'provisional-selection.json', {'status': 'provisionally_selected_for_research',
        'user_authorized_provisional_selection': True, 'primary_model': 'J23',
        'primary_scope': reference['J23']['scope'], 'primary_model_sha256': reference['J23']['model_sha256'],
        'comparison_model': 'V110', 'comparison_scope': reference['V110']['scope'],
        'interpretation': 'J23 primary inferred from preceding priority; V110 remains a separate comparison',
        'formal_performance_adoption': False, 'performance_gate_passed': False,
        'actual_betting_enabled': False, 'quality_flags_overridden': False,
        'forward_protocol_changed': False})
    ledger = json.loads(LEDGER.read_text(encoding='utf-8'))
    jrows = [r for r in ledger['base'] if r['course'] in ('tokyo', 'nakayama') and int(r['race_date'][5:7]) in (9,10,11)]
    vrows = [r for r in ledger['V110_common'] if r['course'] == 'tokyo']
    result = {'J23': diagnose(jrows, 'J23'), 'V110': diagnose(vrows, 'V110')}
    assert result['J23']['total']['bets'] == 145 and result['J23']['total']['payout_yen'] == 174060
    assert result['V110']['total']['bets'] == 429 and result['V110']['total']['payout_yen'] == 377280
    assert hashlib.sha256(LEDGER.read_bytes()).hexdigest() == source_sha
    save(output/'robustness.json', result)
    save(output/'verification.json', {'status': 'passed', 'source_unchanged': True,
        'prior_totals_match': True, 'halves_reconcile': True,
        'independent_day_checks': sum(v['independent_day_omission_checks'] for v in result.values()),
        'new_fits': 0, 'sql_calls': 0, 'http_calls': 0, 'formal_performance_adoption': False})
    print(json.dumps({name: {'total': v['total'], 'halves': v['chronological_buy_day_halves'],
        'leave_year_ROI': {y:s['roi'] for y,s in v['leave_one_year_out'].items()},
        'day_omission': {k:s for k,s in v['leave_one_buy_day_out'].items() if k!='all'}}
        for name,v in result.items()}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
