"""概要: SQL履歴メタデータと公式馬集合が不変の場合だけ検証済み15特徴を再利用する。
作成日: 2026-10-25
入力: 新公式snapshot、前回snapshot、保存済みD0の入力束。
出力: 新snapshot配下inputの特徴/品質とhistory-metadata-check.json。
実行例: uv run --frozen python scripts/reuse_jra_chimera_public_input.py --snapshot artifacts/predictions/20261025-early-snapshot
注意事項: SQL SELECTのみ、原文再読取/再学習なし。馬集合や履歴変更時は停止する。
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

import mssql_python

from jra_srb.jra_research_reader import research_connection_string

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'artifacts/predictions/20261025-condition-chimera'
REFERENCE = ROOT/'artifacts/predictions/20261025-attribute-chimera-v2'


def read(path):
    """UTF-8の保存JSONを読み込む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    """新規証跡をUTF-8 JSONで保存し、既存ファイルは上書きしない。"""
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def reuse(folder):
    """原文の保存SHA列と馬集合/直近走を照合し、変化がない時だけ特徴を再利用する。

    Raises:
        AssertionError: 履歴/カード/入力の不一致、欠測、発走後。
    Notes:
        履歴SHA列が一致しても最新競走まで収録されている保証にはならない。
        接続情報・原文は保存せず、SQL失敗時に自動再試行しない。
    """
    card, prior_card = read(folder/'official-card.json'), read(OLD/'official-card.json')
    public, prior_quality = read(OLD/'input/input.json'), read(OLD/'input/quality.json')
    reference = read(REFERENCE/'input.json')
    assert public == reference['public_features']
    assert hashlib.sha256((OLD/'official-card.json').read_bytes()).hexdigest() == prior_quality['card_sha256']
    assert card['race_id'] == public['race_id'] == prior_card['race_id']
    assert all(card[key] == prior_card[key] for key in ('surface', 'distance', 'start_time'))
    assert card['data_status']['runner_set'] == 'complete' and card['data_status']['source_kind'] == 'pre_race_card'
    now = datetime.now(timezone.utc)
    start = re.fullmatch(r'(\d{1,2})時(\d{2})分', card['start_time'])
    assert start is not None
    post = datetime.fromisoformat(f"{public['race_date']}T{int(start[1]):02d}:{int(start[2]):02d}:00+09:00")
    assert now < post and public['race_date'].startswith('2026-')
    observed = datetime.fromisoformat(card['fetched_at'].replace('Z', '+00:00'))
    assert timedelta(0) <= now-observed <= timedelta(hours=1)
    old_rows = {int(r['horse_no']): r for r in prior_card['runners'] if r['status'] == 'active'}
    new_rows = {int(r['horse_no']): r for r in card['runners'] if r['status'] == 'active'}
    assert len(new_rows) == len(old_rows) == len(public['horses']) and set(new_rows) == set(old_rows)
    for number, row in new_rows.items():
        assert all(row[key] == old_rows[number][key] for key in ('horse_name', 'sex_age'))
        assert row['official_recent_races'] == old_rows[number]['official_recent_races']
    # 取込済み2026年は固定snapshot27。型・年条件は旧readerと同一。
    connection = mssql_python.connect(research_connection_string(), autocommit=True)
    connection.timeout = 15
    try:
        cursor = connection.cursor()
        cursor.execute('SELECT TOP (50001) __migration_source_rowid,record_type,race_key,is_valid,sha256 '
            'FROM raw.year_raw_records WHERE __migration_source_snapshot_id=? AND record_type IN (?,?) '
            'ORDER BY __migration_source_rowid', (27, 'RA', 'SE'))
        rows = cursor.fetchall()
        cursor.close()
    finally:
        connection.close()
    assert len(rows) <= 50000
    stream, counts, latest = hashlib.sha256(), {}, None
    for rowid, kind, key, valid, sha in rows:
        counts[kind] = counts.get(kind, 0)+1
        if valid and key and key.startswith('2026') and key[:8] < public['race_date'].replace('-', ''):
            stream.update((str(rowid)+':'+sha+'\n').encode())
            latest = max(latest or key[:8], key[:8])
    prior = prior_quality['additional_coverage']['2026']
    check = {'source': 'raw.year_raw_records snapshot27 RA/SE metadata only', 'rows': len(rows), 'counts': counts,
        'latest_raw_day': latest, 'input_digest': stream.hexdigest(), 'prior_digest': prior['input_digest'],
        'unchanged': stream.hexdigest() == prior['input_digest'], 'checked_at': now.isoformat(), 'payloads_read': False}
    save(folder/'history-metadata-check.json', check)
    assert check['unchanged'] and all(counts[kind] == prior['scanned_'+kind] for kind in ('RA', 'SE'))
    out = folder/'input'
    out.mkdir(exist_ok=False)
    save(out/'input.json', public)
    save(out/'quality.json', {**prior_quality, 'card_sha256': hashlib.sha256((folder/'official-card.json').read_bytes()).hexdigest(),
        'card_fetched_at': card['fetched_at'], 'prepared_at': now.isoformat(), 'reused_public_features': True,
        'public_input_source': str((OLD/'input/input.json').relative_to(ROOT)), 'public_input_sha256': hashlib.sha256((OLD/'input/input.json').read_bytes()).hexdigest(),
        'latest_history_metadata_checked_at': now.isoformat(), 'history_metadata_unchanged': True,
        'all_course_history_latest_verified': False, 'reference_only': True})
    print(json.dumps(check))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    try:
        reuse(args.snapshot)
    except Exception as error:
        save(args.snapshot/'refresh-failure.json', {'type': type(error).__name__, 'stage': 'input_reuse', 'sql_writes': 0})
        raise
