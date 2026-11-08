"""概要: 条件別選別の年境界・標本不足・見送り精算を検証する。
作成日: 2026-11-07
入力: 合成の複数年購入行。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_condition_gate.py
注意事項: 外部通信・実購入・ファイル変更なし。
"""

import pytest
from jra_srb import jra_research_condition_gate as gate


def rows(year, paid=200, course=5):
    """30日各1件の固定購入行を作る。"""
    return [{'race_id': f'{year}{i:08d}', 'race_date': f'{year}-{1+i//28:02d}-{1+i%28:02d}',
             'course': course, 'surface': 0, 'distance': 1600, 'indices': [0],
             'tickets': 1, 'stake_yen': 100, 'paid_yen': paid, 'hits': int(paid > 0)}
            for i in range(30)]


def test_future_outcome_changes_never_change_previous_gate():
    """当年の払戻を書換えても当年購入可否の選別証跡は変わらない。"""
    train = rows(2023)
    a, audit_a = gate.walk_forward(train + rows(2024, 0), 'course', False)
    b, audit_b = gate.walk_forward(train + rows(2024, 10000), 'course', False)
    assert audit_a['2024'] == audit_b['2024']
    assert [r['tickets'] for r in a] == [r['tickets'] for r in b] == [1] * 30
    assert audit_a['2025']['accepted_groups'] != audit_b['2025']['accepted_groups']


def test_insufficient_or_unseen_group_never_falls_back():
    """29件しかない群や未観測場では、他群が黒字でも購入しない。"""
    out, _ = gate.walk_forward(rows(2023)[:29] + rows(2024), 'course', False)
    assert all(r['tickets'] == r['paid_yen'] == r['hits'] == 0 for r in out)
    out, _ = gate.walk_forward(rows(2023) + rows(2024, course=8), 'course', False)
    assert all(r['indices'] == [] and r['stake_yen'] == 0 for r in out)


def test_stable_gate_rejects_red_year_despite_pooled_profit():
    """通算黒字でも過去1年が赤字なら年安定型だけ拒否する。"""
    history = rows(2023, 300) + rows(2024, 0)
    assert gate.evidence(history, False)['accepted']
    assert not gate.evidence(history, True)['accepted']


@pytest.mark.parametrize('distance,band', [(1400, '1400'), (1401, '1800'), (1800, '1800'),
                                         (2201, '2600'), (2601, '2601plus')])
def test_distance_boundaries(distance, band):
    """距離帯の境界が固定契約どおりである。"""
    assert gate.distance_band(distance) == band


def test_duplicate_ids_are_refused():
    """同じ競走を複数の教師行として水増しできない。"""
    with pytest.raises(ValueError):
        gate.walk_forward(rows(2023) + rows(2023), 'course', False)
