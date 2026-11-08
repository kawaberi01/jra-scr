"""概要: 期限付き前向き比較の日程と、事前固定した芝限定の派生評価を扱う。
作成日: 2026-11-07
入力: JST時刻、開始/終了日、workerの保存済みpayloadと評価。
出力: 起動窓、翌日以降に限定した芝候補の仮想精算。
実行例: uv run --frozen --extra ml python scripts/run_jra_shadow_series.py --check-only
注意事項: 当日以前への遡及適用・実購入・外部通信なし。
"""

from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def phase(now, first, last):
    """JSTで09〜18時を実行窓とし、過ぎた日を後から実行しない。"""
    now = now.astimezone(JST)
    if first > last or (last - first).days >= 14:
        raise ValueError('series_window_must_be_within_14_days')
    if now.date() > last or (now.date() == last and now.hour >= 18):
        return 'finished'
    if first <= now.date() <= last and 9 <= now.hour < 18:
        return 'active'
    return 'waiting'


def turf_overlay(item, payload, frozen_at, first):
    """凍結後・開始日以降のS0事前予想だけに芝制限を適用する。

    Args:
        item: 既存workerの評価済みS0台帳行。
        payload: 事前保存された対応するpayload。
        frozen_at: 候補条件が固定されたUTCのISO時刻。
        first: 候補の適用開始日。
    Returns:
        dict: 芝限定の仮想支出/払戻/的中と元予想の識別子。
    Raises:
        ValueError: 遡及適用、実購入、未評価、非S0、名簿/時刻不正。
    """
    snap = payload['pre_race_snapshot']
    created = datetime.fromisoformat(payload['created_at'])
    receipt = datetime.fromisoformat(item['server_received_at'])
    post = datetime.fromisoformat(item['post_at'])
    if (item['case'] != 'S0' or item['status'] != 'evaluated'
            or payload['prediction_id'] != item['prediction_id']
            or payload['budget'] != 0 or payload['prediction_tickets']
            or date.fromisoformat(snap['race_date']) < first
            or created <= datetime.fromisoformat(frozen_at) or not created < post or not receipt < post):
        raise ValueError('series_overlay_not_eligible_prerace')
    surface = snap['card']['surface']
    if surface not in ('turf', 'dirt', '芝', 'ダート', 0, 1):
        raise ValueError('series_overlay_unknown_surface')
    include = surface in ('turf', '芝', 0)
    virtual = item.get('research_simulation', {})
    stake = item['virtual_stake_yen'] if include else 0
    if stake and (virtual.get('status') != 'available' or virtual['virtual_stake_yen'] != stake):
        raise ValueError('series_overlay_missing_settlement')
    return {'race_id': item['race_id'], 'race_date': snap['race_date'], 'prediction_id': item['prediction_id'],
            'indices': [], 'tickets': int(stake > 0), 'stake_yen': stake,
            'paid_yen': virtual['virtual_payout_yen'] if stake else 0,
            'hits': int(bool(virtual.get('hit'))) if stake else 0, 'is_turf': include}
