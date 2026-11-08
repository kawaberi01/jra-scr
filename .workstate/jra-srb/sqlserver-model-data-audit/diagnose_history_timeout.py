"""概要: 共通履歴SQLの定義・索引・推定実行計画を読取専用で採取する。
作成日: 2026-10-18
入力: 既存SQL reader設定、--output-dir、任意の--measureと--variant。
出力: 指定先の新規JSON・SQL・XMLと標準出力の要約。
実行例: uv run python .workstate/jra-srb/sqlserver-model-data-audit/diagnose_history_timeout.py --output-dir artifacts/diagnostics/history-timeout-20261018
注意事項: SQLite・当日結果を読まない。DDL・業務更新・永続設定変更なし。
    測定は各SQL1回、既存30秒設定に加えプロセスの40秒上限を使用する。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import threading
import xml.etree.ElementTree as ET

from jra_srb.sqlserver_db import SqlServerConnection, compile_sql
from jra_srb.sqlserver_schema import ANALYSIS_TABLES
from jra_srb.storage_config import SqlServerSettings, storage_backend


def history_query():
    """実コードの対象関数からSELECT文字列を抽出し、SQL Server版を返す。"""
    tree = ast.parse(Path('src/jra_srb/jra_history_dataset.py').read_text(encoding='utf-8-sig'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_live_feature_records')
    call = next(n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'execute')
    original = ast.literal_eval(call.args[0])
    return original, compile_sql(original, ANALYSIS_TABLES)


def safe_error(error):
    """秘密値を含めず診断可能な例外種別と既知の理由を返す。"""
    message = str(error).lower()
    reasons = [key for key in ('timeout', 'permission', 'denied', 'showplan', 'invalid column', 'view server') if key in message]
    return {'error_type': type(error).__name__, 'reasons': reasons}


def measure(output_dir, settings, statement, indices, selected):
    """指定した診断差分だけを1回測定し、取得行数と結果集合のdigestを保存する。

    Notes:
        各接続は既存の30秒設定を維持し、40秒で診断プロセスを終了する。
        差分SQLは診断専用であり、
        本番実装やDB設定へ反映しない。実行後は接続を閉じる。
    """
    base, order = statement.rsplit(' ORDER BY ', 1)
    variants = {'original': statement, 'without_order': base,
                'rank_not_null': base + ' AND [re].[rank] IS NOT NULL ORDER BY ' + order,
                'hash_join': statement + ' OPTION (HASH JOIN)',
                'recompile': statement + ' OPTION (RECOMPILE)'}
    results = []
    for name, sql in variants.items():
        if selected != name:
            continue
        result_path = output_dir / ('timing-' + name + '.json')
        assert not result_path.exists()
        def expire():
            """40秒超過を記録し、この診断プロセスだけを終了する。"""
            expired = {'variant': name, 'status': 'wall_timeout', 'wall_limit_seconds': 40}
            result_path.write_text(json.dumps(expired)+'\n', encoding='utf-8')
            print(json.dumps(expired), flush=True)
            os._exit(124)
        watchdog = threading.Timer(40, expire)
        watchdog.daemon = True
        watchdog.start()
        connection = SqlServerConnection(settings, ANALYSIS_TABLES, read_only=True)
        started = time.perf_counter()
        result = {'variant': name}
        try:
            rows = connection._raw(sql, ['2026-10-18' for _ in indices]).fetchall()
            result.update(status='passed', elapsed_seconds=time.perf_counter()-started, rows=len(rows),
                          null_ranks=sum(row['rank'] is None for row in rows))
            hashes = sorted(hashlib.sha256(json.dumps(list(row), ensure_ascii=False, default=str).encode('utf-8')).hexdigest() for row in rows)
            result['multiset_sha256'] = hashlib.sha256('\n'.join(hashes).encode()).hexdigest()
            del rows, hashes
        except Exception as error:
            result.update(status='failed', elapsed_seconds=time.perf_counter()-started, **safe_error(error))
        finally:
            connection.close()
        watchdog.cancel()
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return results


def main():
    """読取roleでメタデータと非実行の推定計画を新規成果物へ保存する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--measure', action='store_true', help='既存成果物先へ指定したSQLを1回測定する')
    parser.add_argument('--variant', choices=('original', 'without_order', 'rank_not_null', 'hash_join', 'recompile'), default='original')
    args = parser.parse_args()
    assert storage_backend() == 'sqlserver'
    settings = SqlServerSettings.from_env()
    original, (statement, indices) = history_query()
    if args.measure:
        assert args.output_dir.is_dir()
        measure(args.output_dir, settings, statement, indices, args.variant)
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'original.sql').write_text(original, encoding='utf-8')
    (args.output_dir / 'compiled.sql').write_text(statement, encoding='utf-8')
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'timeout_seconds': settings.timeout_seconds,
              'parameter_indices': indices, 'business_writes': 0, 'sqlite_used': False}
    queries = {
        'database': "SELECT DB_NAME() database_name, compatibility_level, is_auto_create_stats_on, is_auto_update_stats_on FROM sys.databases WHERE name=DB_NAME()",
        'permissions': "SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','SHOWPLAN') showplan, HAS_PERMS_BY_NAME(NULL,'SERVER','VIEW SERVER STATE') server_state, HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','VIEW DATABASE STATE') database_state",
        'counts': "SELECT t.name,SUM(p.rows) row_count FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN(0,1) WHERE s.name=N'api_runtime' AND t.name IN(N'races',N'runners',N'result_entries',N'payouts') GROUP BY t.name",
        'indexes': "SELECT t.name table_name,i.name index_name,i.type_desc,i.is_disabled,i.has_filter,i.filter_definition,c.name column_name,ic.key_ordinal,ic.is_included_column FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.indexes i ON i.object_id=t.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE s.name=N'api_runtime' AND t.name IN(N'races',N'runners',N'result_entries',N'payouts') ORDER BY t.name,i.index_id,ic.index_column_id",
        'column_types': "SELECT t.name table_name,c.name column_name,ty.name type_name,c.max_length,c.is_computed FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id WHERE s.name=N'api_runtime' AND t.name IN(N'races',N'runners',N'result_entries',N'payouts') AND (c.name IN(N'race_id',N'race_date',N'horse_no',N'source') OR c.name LIKE N'__hash%') ORDER BY t.name,c.column_id",
        'stats': "SELECT t.name table_name,st.name stats_name,STATS_DATE(st.object_id,st.stats_id) updated_at,st.auto_created,st.user_created,st.no_recompute FROM sys.stats st JOIN sys.tables t ON t.object_id=st.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=N'api_runtime' AND t.name IN(N'races',N'runners',N'result_entries',N'payouts') ORDER BY t.name,st.stats_id",
    }
    connection = SqlServerConnection(settings, ANALYSIS_TABLES, read_only=True)
    try:
        for name, query in queries.items():
            try:
                report[name] = [dict(row) for row in connection._raw(query).fetchall()]
            except Exception as error:
                report[name] = safe_error(error)
        try:
            connection._raw('SET SHOWPLAN_XML ON')
            cursor = connection._connection.cursor()
            try:
                cursor.execute(statement, tuple('2026-10-18' for _ in indices))
                xml = str(cursor.fetchone()[0])
            finally:
                cursor.close()
            (args.output_dir / 'estimated-plan.xml').write_text(xml, encoding='utf-8')
            tree = ET.fromstring(xml)
            report['plan'] = [{'tag': el.tag.rsplit('}', 1)[-1], **el.attrib} for el in tree.iter()
                              if el.tag.rsplit('}', 1)[-1] in ('RelOp', 'Object', 'MemoryGrantInfo', 'MissingIndex', 'OptimizerStatsUsage', 'Warnings')]
        except Exception as error:
            report['plan'] = safe_error(error)
        finally:
            connection._raw('SET SHOWPLAN_XML OFF')
    finally:
        connection.close()
    (args.output_dir / 'metadata.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('timeout_seconds', 'database', 'permissions', 'counts')}, ensure_ascii=False, default=str))
    print('PLAN', 'saved' if isinstance(report['plan'], list) else report['plan'])
    print('OUTPUT', args.output_dir)


if __name__ == '__main__':
    main()
