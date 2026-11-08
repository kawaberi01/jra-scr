"""概要: 固定候補の発走前予想を仮想購入だけの保存payloadへ変換する。
作成日: 2026-11-07
入力: 検算済みモデル確率、実オッズ、発走時刻、事前snapshot。
出力: UUID予想、仮想買い目、実購入0円のSQL保存用payload。
実行例: uv run --frozen --extra ml python scripts/run_jra_research_shadow.py --once
注意事項: 当関数は結果を参照しない。実購入ticketsと仮想買い目を混在させない。
"""

from datetime import datetime, timezone
from itertools import combinations
from uuid import uuid4
import numpy as np
from . import jra_research_purchase_portfolio as policies


def payload(record, probabilities, prices, snapshot, model_id, model_sha256, rule, post_at, now=None):
    """発走前だけUUID予想を作り、固定1点を仮想欄に分離する。"""
    now = now or datetime.now(timezone.utc)
    post = datetime.fromisoformat(post_at)
    if now.tzinfo is None or post.tzinfo is None or (post - now).total_seconds() < 30:
        raise ValueError('not_safely_before_post')
    p, o = np.asarray(probabilities), np.asarray(prices)
    pairs = list(combinations(record['horses'], 2))
    if len(p) != len(pairs) or len(o) != len(pairs) or abs(float(p.sum()) - 1) > 1e-8:
        raise ValueError('forecast_roster_or_probability')
    selected = policies.select(p, o)[rule]
    if len(selected) > 1:
        raise ValueError('shadow_requires_single_ticket')
    plan_tickets = [{'bet_type': 'quinella', 'selection': list(pairs[i]), 'amount': 100,
                     'odds': float(o[i]), 'probability': float(p[i]), 'expected_return': float(p[i] * o[i])}
                    for i in selected]
    ranking = [{'horses': list(pairs[i]), 'probability': float(p[i]), 'odds': float(o[i])}
               for i in sorted(range(len(p)), key=lambda i: (-p[i], i))]
    forecast = {'race_id': record['race_id'], 'generated_before_result': True, 'reconstruction_after_result': False,
        'finish_order_prediction_available': False, 'predicted_top3': [], 'pair_ranking': ranking,
        'probability_capabilities': ['quinella'], 'purchase_allowed': False, 'purchase_yen': 0,
        'selected_model': {'model_id': model_id, 'model_sha256': model_sha256, 'usage_status': 'research_only',
                           'trained_through': '2025-12-28'},
        'input_state': {'market_timing': snapshot['timing'], 'post_at': post_at, 'observed_at': snapshot['observed_at'],
                        'runner_status_parser': 'spec452-current-cells-only'},
        'research_plan': {'status': 'available' if selected else 'unavailable', 'virtual_only': True,
            'policy_id': f'spec453:{model_id}:{rule}', 'virtual_budget_yen': len(selected) * 100,
            'total_stake_yen': len(selected) * 100, 'tickets': plan_tickets,
            'reason': None if selected else '固定購入条件に該当する馬連なし'}}
    forecast['display_text'] = f"{record['race_id']} {model_id} {rule}: 仮想{len(selected) * 100}円、実購入0円。馬連上位 " + ', '.join('-'.join(r['horses']) for r in ranking[:3])
    return {'prediction_id': f"jra-shadow-{record['race_id']}-{uuid4()}", 'race_id': record['race_id'],
        'theory_version': f'spec453:{model_id}:{rule}', 'mode': 'research_shadow', 'budget': 0,
        'created_at': now.isoformat(), 'pre_race_snapshot': snapshot, 'prediction_json': forecast, 'prediction_tickets': []}
