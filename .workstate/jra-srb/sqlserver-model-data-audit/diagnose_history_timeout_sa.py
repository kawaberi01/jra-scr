"""概要: 今回限りのsa接続で共通履歴SELECTの計画と待機を読み取り診断する。
作成日: 2026-10-18
入力: --output-dir、--phase、既存2022接続helperとローカル.env。
出力: 新規診断ディレクトリ内のJSON・対象クエリの計画XML、標準出力の要約。
実行例: uv run python .workstate/jra-srb/sqlserver-model-data-audit/diagnose_history_timeout_sa.py --output-dir artifacts/diagnostics/history-timeout-sa-20261018 --phase cache
注意事項: 利用者が明示した今回の調査専用。認証値を出力・保存しない。
    DDL・DML・権限付与・統計更新・設定変更・他session停止・SQLite参照なし。
    observeでは通常readerの元SELECTを1回だけ実行し、45秒で専用プロセスを終了する。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import xml.etree.ElementTree as ET

from diagnose_history_timeout import history_query, safe_error
from jra_srb.sqlserver_db import SqlServerConnection
from jra_srb.sqlserver_schema import ANALYSIS_TABLES
from jra_srb.storage_config import SqlServerSettings


def connect_sa():
    """既存helperで秘密をメモリだけに読み、固定2022の対象DBへ接続する。"""
    sys.path.insert(0, 'D:/develop/jra-van-data/tools')
    import sqlserver_unified_runtime as runtime
    values = runtime.provision.read_dotenv()
    password = runtime.provision.get_secret('MSSQL_SA_PASSWORD', values, True)
    connection = runtime.connect({'MSSQL_SA_PASSWORD': password}, database='jra_unified', role='sa')
    connection.timeout = 10
    identity = select(connection, "SELECT DB_NAME() database_name,ORIGINAL_LOGIN() login_name,IS_SRVROLEMEMBER('sysadmin') sysadmin,CONVERT(int,SERVERPROPERTY('ProductMajorVersion')) major_version")[0]
    if identity != {'database_name': 'jra_unified', 'login_name': 'sa', 'sysadmin': 1, 'major_version': 16}:
        connection.close()
        raise RuntimeError('unexpected_admin_identity')
    return connection, identity


def select(connection, sql, params=()):
    """固定されたSELECTを実行し、cursorを閉じて辞書行を返す。"""
    if not sql.lstrip().upper().startswith('SELECT'):
        raise ValueError('only_select_allowed')
    cursor = connection.cursor()
    try:
        cursor.execute(sql, tuple(params))
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def save_json(path, value):
    """秘密を含まない観測結果をUTF-8新規ファイルへ保存する。"""
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n')


def plan_summary(xml):
    """計画から結合・走査・推定件数・警告とメモリ情報を抽出する。"""
    root = ET.fromstring(xml)
    ns = {'p': 'http://schemas.microsoft.com/sqlserver/2004/07/showplan'}
    operators = []
    for operator in root.findall('.//p:RelOp', ns):
        item = dict(operator.attrib)
        item['objects'] = [obj.attrib for obj in operator.findall('./*/p:Object', ns)]
        item['runtime'] = [node.attrib for node in operator.findall('./p:RunTimeInformation/p:RunTimeCountersPerThread', ns)]
        operators.append(item)
    return {'operators': operators,
            'statements': [node.attrib for node in root.findall('.//p:StmtSimple', ns)],
            'memory': [node.attrib for node in root.findall('.//p:MemoryGrantInfo', ns)],
            'warnings': [ET.tostring(node, encoding='unicode') for node in root.findall('.//p:Warnings', ns)],
            'missing_indexes': [ET.tostring(node, encoding='unicode') for node in root.findall('.//p:MissingIndexes', ns)]}


def cache_phase(connection, output, identity):
    """対象履歴SELECTだけのキャッシュ計画・累積実績・索引定義を採取する。"""
    rows = select(connection, "SELECT TOP (12) qs.plan_handle,qs.creation_time,qs.last_execution_time,qs.execution_count,qs.total_worker_time,qs.total_elapsed_time,qs.total_logical_reads,qs.last_worker_time,qs.last_elapsed_time,qs.last_logical_reads,qs.last_rows,txt.text statement_text,CONVERT(nvarchar(max),qp.query_plan) plan_xml FROM sys.dm_exec_query_stats qs CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) txt OUTER APPLY sys.dm_exec_query_plan(qs.plan_handle) qp WHERE CHARINDEX(?,txt.text)>0 AND CHARINDEX(?,txt.text)>0 ORDER BY qs.last_execution_time DESC",
                  ('SELECT [r].[race_id], [r].[race_date], [r].[race_name]', 'FROM [api_runtime].[races] AS [r]'))
    report = {'identity': identity, 'observed_at': datetime.now(timezone.utc).isoformat(), 'plans': []}
    for index, row in enumerate(rows):
        xml = row.pop('plan_xml')
        handle = bytes(row.pop('plan_handle'))
        row['plan_handle_hex'] = handle.hex()
        row['attributes'] = select(connection, 'SELECT attribute,CONVERT(nvarchar(128),value) value,is_cache_key FROM sys.dm_exec_plan_attributes(?) WHERE attribute IN (N\'dbid\',N\'user_id\',N\'set_options\')', (handle,))
        if xml:
            path = output / f'cached-plan-{index}.xml'
            path.write_text(xml, encoding='utf-8')
            row['plan_summary'] = plan_summary(xml)
        report['plans'].append(row)
    report['indexes'] = select(connection, "SELECT t.name table_name,i.name index_name,i.filter_definition,i.is_disabled,c.name column_name,ic.key_ordinal FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.indexes i ON i.object_id=t.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE s.name=N'api_runtime' AND t.name IN(N'races',N'runners',N'result_entries',N'payouts') ORDER BY t.name,i.index_id,ic.index_column_id")
    report['stats'] = select(connection, "SELECT t.name table_name,st.name stats_name,p.last_updated,p.rows,p.rows_sampled,p.modification_counter FROM sys.stats st JOIN sys.tables t ON t.object_id=st.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id OUTER APPLY sys.dm_db_stats_properties(st.object_id,st.stats_id) p WHERE s.name=N'api_runtime' AND t.name IN(N'races',N'runners',N'result_entries',N'payouts') ORDER BY t.name,st.stats_id")
    save_json(output / 'cache-report.json', report)
    print('SA_IDENTITY', json.dumps(identity), flush=True)
    for index, row in enumerate(report['plans']):
        operators = row.get('plan_summary', {}).get('operators', [])
        print('PLAN', index, 'executions', row['execution_count'], 'last_ms', row['last_elapsed_time']/1000,
              'last_reads', row['last_logical_reads'], 'joins', [(r['NodeId'],r['PhysicalOp'],r.get('EstimateRows')) for r in operators if 'Join' in r['LogicalOp']], flush=True)


def observe_phase(connection, output, identity):
    """通常readerの元SQLを1回だけ再現し、対象sessionの待機と実行中計画を観測する。"""
    _, (statement, indices) = history_query()
    report = {'identity': identity, 'started_at': datetime.now(timezone.utc).isoformat(), 'samples': [], 'reader_result': {}}
    started = threading.Event()
    done = threading.Event()
    def reader_run():
        """通常readerを専用threadで所有し、元クエリを1回だけ実行する。"""
        reader = None
        begin = time.perf_counter()
        try:
            reader = SqlServerConnection(SqlServerSettings.from_env(), ANALYSIS_TABLES, read_only=True)
            report['reader_spid'] = reader._raw('SELECT @@SPID spid').fetchone()[0]
            started.set()
            result = reader._raw(statement, ['2026-10-18' for _ in indices]).fetchall()
            report['reader_result'] = {'status': 'passed', 'rows': len(result), 'elapsed_seconds': time.perf_counter()-begin}
        except Exception as error:
            report['reader_result'] = {'status': 'failed', 'elapsed_seconds': time.perf_counter()-begin, **safe_error(error)}
        finally:
            if reader is not None:
                reader.close()
            done.set()
    def expire():
        """45秒でこの専用診断プロセスを終了し、採取済み証跡を残す。"""
        report['wall_timeout'] = True
        save_json(output / 'observe-wall-timeout.json', report)
        os._exit(124)
    watchdog = threading.Timer(45, expire)
    watchdog.daemon = True
    watchdog.start()
    worker = threading.Thread(target=reader_run, daemon=True)
    worker.start()
    started.wait(10)
    if not started.is_set():
        raise RuntimeError('reader_start_failed')
    for index in range(6):
        if done.wait(4):
            break
        spid = report['reader_spid']
        sample = {'observed_at': datetime.now(timezone.utc).isoformat()}
        sample['request'] = select(connection, 'SELECT session_id,status,command,cpu_time,total_elapsed_time,logical_reads,reads,writes,wait_type,wait_time,last_wait_type,wait_resource,blocking_session_id,granted_query_memory,dop,parallel_worker_count FROM sys.dm_exec_requests WHERE session_id=?', (spid,))
        sample['memory'] = select(connection, 'SELECT requested_memory_kb,granted_memory_kb,required_memory_kb,used_memory_kb,max_used_memory_kb,wait_time_ms FROM sys.dm_exec_query_memory_grants WHERE session_id=?', (spid,))
        report['samples'].append(sample)
        print('SAMPLE', json.dumps(sample, default=str), flush=True)
        if index == 2:
            try:
                plans = select(connection, 'SELECT CONVERT(nvarchar(max),query_plan) plan_xml FROM sys.dm_exec_query_statistics_xml(?)', (spid,))
                if plans and plans[0]['plan_xml']:
                    xml = plans[0]['plan_xml']
                    (output / 'live-plan.xml').write_text(xml, encoding='utf-8')
                    report['live_plan_summary'] = plan_summary(xml)
            except Exception as error:
                report['live_plan_error'] = safe_error(error)
    done.wait(10)
    watchdog.cancel()
    save_json(output / 'observe-report.json', report)
    print('READER_RESULT', json.dumps(report['reader_result']), flush=True)


def main():
    """明示したsa診断phaseだけを実行し、接続を必ず閉じる。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=('cache', 'observe'), required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=args.phase == 'observe')
    connection = None
    try:
        connection, identity = connect_sa()
        {'cache': cache_phase, 'observe': observe_phase}[args.phase](connection, args.output_dir, identity)
    except Exception as error:
        failure = safe_error(error)
        save_json(args.output_dir / (args.phase+'-failure.json'), failure)
        print('FAILED', json.dumps(failure), flush=True)
        raise SystemExit(1) from None
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    main()
