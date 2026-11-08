"""概要: 前年までの条件別購入実績で翌年の購入可否を固定する。
作成日: 2026-11-07
入力: 条件属性と固定候補の過去精算行、区分名、年安定条件。
出力: 年境界を保持した購入マスクと選別証跡。
実行例: uv run --frozen --extra ml python scripts/run_jra_condition_gate.py
注意事項: 同年以降の結果を選別に使わない。実購入・外部通信なし。
"""

from collections import defaultdict

DIMENSIONS = ('course', 'distance', 'surface', 'course_surface', 'surface_distance')


def distance_band(distance):
    """メートル単位の距離を事前固定の5帯へ割り当てる。"""
    for bound in (1400, 1800, 2200, 2600):
        if int(distance) <= bound:
            return str(bound)
    return '2601plus'


def group_key(row, dimension):
    """結果を使わず競走属性だけから条件区分を返す。"""
    course, surface = str(int(row['course'])), str(int(row['surface']))
    distance = distance_band(row['distance'])
    return {'course': course, 'distance': distance, 'surface': surface,
            'course_surface': course + ':' + surface,
            'surface_distance': surface + ':' + distance}[dimension]


def evidence(rows, stable):
    """過去の購入数・的中・日数・黒字と、任意の年別安定条件を判定する。"""
    bought = [r for r in rows if r['tickets']]
    yearly = defaultdict(lambda: {'tickets': 0, 'net_yen': 0})
    for row in bought:
        cell = yearly[row['race_date'][:4]]
        cell['tickets'] += row['tickets']
        cell['net_yen'] += row['paid_yen'] - row['stake_yen']
    tickets = sum(r['tickets'] for r in bought)
    hits = sum(r['hits'] for r in bought)
    days = len({r['race_date'] for r in bought})
    net = sum(r['paid_yen'] - r['stake_yen'] for r in bought)
    accepted = tickets >= 30 and hits >= 5 and days >= 10 and net > 0
    if stable:
        accepted = accepted and all(v['tickets'] >= 10 and v['net_yen'] > 0 for v in yearly.values())
    return {'accepted': bool(accepted), 'tickets': tickets, 'hits': hits, 'days': days,
            'net_yen': net, 'annual': dict(yearly),
            'latest_training_date': max((r['race_date'] for r in rows), default=None)}


def walk_forward(rows, dimension, stable):
    """2024〜26年それぞれに前年以前だけで条件を選別し、見送りも残す。

    Args:
        rows: 2023年以降の属性付き固定選択・精算行。重複IDは拒否する。
        dimension: DIMENSIONSにある固定区分。
        stable: 過去年別の件数・黒字条件も要求するか。
    Returns:
        tuple: 全評価機会の派生精算行と、年ごとの選別証跡。
    Raises:
        ValueError: 区分不正、複数点、ID重複など契約違反。
    Notes:
        見送り行では選択/金額/的中を0にし、元候補の精算は変更しない。
    """
    if dimension not in DIMENSIONS or len({r['race_id'] for r in rows}) != len(rows):
        raise ValueError('gate_dimension_or_duplicate')
    if any(r['tickets'] not in (0, 1) for r in rows):
        raise ValueError('gate_single_ticket_only')
    result, audit = [], {}
    for year in (2024, 2025, 2026):
        cutoff = f'{year}-01-01'
        train = [r for r in rows if r['race_date'] < cutoff]
        test = [r for r in rows if r['race_date'].startswith(str(year))]
        grouped = defaultdict(list)
        for r in train:
            grouped[group_key(r, dimension)].append(r)
        cells = {key: evidence(rr, stable) for key, rr in sorted(grouped.items())}
        chosen = {key for key, cell in cells.items() if cell['accepted']}
        audit[str(year)] = {'train_ids': [r['race_id'] for r in train],
                            'test_ids': [r['race_id'] for r in test], 'groups': cells,
                            'accepted_groups': sorted(chosen)}
        for r in test:
            accept = group_key(r, dimension) in chosen
            result.append(r | {'indices': r['indices'] if accept else [],
                              'tickets': r['tickets'] if accept else 0,
                              'stake_yen': r['stake_yen'] if accept else 0,
                              'paid_yen': r['paid_yen'] if accept else 0,
                              'hits': r['hits'] if accept else 0})
    return result, audit
