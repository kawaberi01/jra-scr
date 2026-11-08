"""概要: SQL Server統合DBをreaderで調査し、モデル検証前のデータ証跡を保存する。
作成日: 2026-10-15
入力: jra-van-dataの既存接続helperとローカル秘密設定、任意の調査フェーズ。
出力: 同じフォルダーのphase別JSON。各照会のSQL・結果・所要時間を保存する。
実行例: uv run python .workstate/jra-srb/sqlserver-model-data-audit/inspect_data.py inventory
注意事項: DBへの更新・再取込なし。readerのみを使用し、失敗時は後続を止める。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, "D:/develop/jra-van-data/tools")
import sqlserver_unified_runtime as runtime


QUERIES = {
    "inventory": {
        "identity": "SELECT DB_NAME() database_name,CURRENT_USER database_user,IS_ROLEMEMBER('db_owner') is_owner,HAS_PERMS_BY_NAME(NULL,'DATABASE','INSERT') can_insert,HAS_PERMS_BY_NAME(NULL,'DATABASE','UPDATE') can_update,HAS_PERMS_BY_NAME(NULL,'DATABASE','DELETE') can_delete",
        "metadata_counts": "SELECT s.name schema_name,t.name table_name,SUM(p.rows) metadata_rows FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN(0,1) GROUP BY s.name,t.name ORDER BY s.name,t.name",
        "adopted_sources": "SELECT d.source_key,d.family,c.source_snapshot_id,s.status,s.captured_at_utc FROM ops.current_source_snapshot c JOIN ops.source_database d ON d.source_database_id=c.source_database_id JOIN ops.source_snapshot s ON s.source_snapshot_id=c.source_snapshot_id ORDER BY d.source_key",
        "migration_tables": "SELECT s.source_snapshot_id,s.status,COUNT_BIG(*) tables,SUM(s.expected_row_count) expected_rows,SUM(s.loaded_row_count) loaded_rows,SUM(CASE WHEN s.expected_row_count<>s.loaded_row_count THEN 1 ELSE 0 END) mismatched_tables FROM ops.source_table s GROUP BY s.source_snapshot_id,s.status ORDER BY s.source_snapshot_id",
        "migration_batches": "SELECT status,COUNT_BIG(*) batches,SUM(source_count) source_rows,SUM(inserted_count) inserted_rows,SUM(CASE WHEN source_batch_sha256<>target_batch_sha256 THEN 1 ELSE 0 END) hash_mismatches FROM ops.import_batch GROUP BY status",
        "source_tables": "SELECT d.source_key,t.source_table_name,t.target_schema,t.target_table,t.expected_row_count,t.loaded_row_count,t.status FROM ops.source_table t JOIN ops.current_source_snapshot c ON c.source_snapshot_id=t.source_snapshot_id JOIN ops.source_database d ON d.source_database_id=c.source_database_id ORDER BY d.source_key,t.source_table_name",
        "build_summary": "SELECT [key],value_json FROM ops.source_build_manifest WHERE [key] IN ('run_status','coverage_summary','candidate_stage_complete','history_checkpoint')",
        "build_asof": "SELECT JSON_VALUE(value_json,'$.config.as_of') build_as_of,JSON_VALUE(value_json,'$.config.schema_version') schema_version,JSON_VALUE(value_json,'$.config.odds_parser_version') odds_parser_version FROM ops.source_build_manifest WHERE [key]='build_identity'",
        "runtime_state": "SELECT state_key,value_json FROM api_runtime.storage_state",
        "coverage_columns": "SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA IN ('history','market','prediction','ops') AND TABLE_NAME IN ('source_coverage','races','features_asof','odds_asof_index','labels') ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION",
    },
    "coverage": {
        "coverage": "SELECT period,dimension,status,[count],evidence_json FROM ops.source_coverage ORDER BY period,dimension,status",
        "race_years": "SELECT LEFT(race_date,4) race_year,COUNT_BIG(*) races,MIN(race_date) first_date,MAX(race_date) last_date,SUM(CASE WHEN start_at IS NULL THEN 1 ELSE 0 END) missing_start_at FROM history.races WHERE __migration_source_snapshot_id=31 GROUP BY LEFT(race_date,4) ORDER BY race_year",
        "race_status": "SELECT status,feature_eligibility,start_time_status,COUNT_BIG(*) races FROM history.races WHERE __migration_source_snapshot_id=31 GROUP BY status,feature_eligibility,start_time_status ORDER BY status,feature_eligibility",
        "venues": "SELECT venue_code,COUNT_BIG(*) races FROM history.races WHERE __migration_source_snapshot_id=31 GROUP BY venue_code ORDER BY venue_code",
        "identity": "SELECT source_system,source_relation,mapping_status,COUNT_BIG(*) mappings FROM history.race_identity_map GROUP BY source_system,source_relation,mapping_status ORDER BY source_system,source_relation,mapping_status",
        "label_status": "SELECT settlement_status,abnormal_code,COUNT_BIG(*) entries,SUM(CASE WHEN rank IS NULL THEN 1 ELSE 0 END) null_rank,SUM(CASE WHEN official_win_settlement IS NULL THEN 1 ELSE 0 END) null_settlement,SUM(CASE WHEN rank=1 THEN 1 ELSE 0 END) winners FROM history.labels WHERE __migration_source_snapshot_id=31 GROUP BY settlement_status,abnormal_code ORDER BY settlement_status,abnormal_code",
        "odds_selection": "SELECT horizon,market,selection_status,COUNT_BIG(*) observations,MIN(cutoff_at) first_cutoff,MAX(cutoff_at) last_cutoff,SUM(CASE WHEN announced_at>cutoff_at THEN 1 ELSE 0 END) announcement_after_cutoff,SUM(CASE WHEN content_sha256 IS NULL THEN 1 ELSE 0 END) no_content FROM market.odds_asof_index WHERE __migration_source_snapshot_id=31 GROUP BY horizon,market,selection_status ORDER BY horizon,market,selection_status",
        "parsed_imports": "SELECT status,parser_version,COUNT_BIG(*) runs,SUM(parsed_records) parsed_records,SUM(rejected_records) rejected_records FROM market.parsed_import_runs GROUP BY status,parser_version",
        "raw_coverage": "SELECT scope,record_type,status,COUNT_BIG(*) coverage_rows,MIN(period) first_period,MAX(period) last_period FROM raw.master_coverage GROUP BY scope,record_type,status ORDER BY scope,record_type,status",
        "live_years": "SELECT LEFT(race_date,4) race_year,source,COUNT_BIG(*) races,MIN(race_date) first_date,MAX(race_date) last_date FROM api_runtime.races GROUP BY LEFT(race_date,4),source ORDER BY race_year,source",
        "feature_sample": "SELECT TOP (4) race_key,horse_no,horizon,market_cutoff_at,o1_announced_at,o2_announced_at,features_json,masked_feature_names_json,feature_status FROM prediction.features_asof WHERE __migration_source_snapshot_id=31",
        "label_sample": "SELECT TOP (4) race_key,horse_no,rank,abnormal_code,official_win_settlement,settlement_status FROM history.labels WHERE __migration_source_snapshot_id=31",
        "race_sample": "SELECT TOP (3) race_key,race_date,status,start_at,feature_eligibility,retrospective_metadata_json FROM history.races WHERE __migration_source_snapshot_id=31",
    },
    "integrity": {
        "race_duplicates": "SELECT COUNT_BIG(*) duplicate_keys FROM (SELECT race_key FROM history.races WHERE __migration_source_snapshot_id=31 GROUP BY race_key HAVING COUNT_BIG(*)>1) d",
        "entry_summary": "SELECT COUNT_BIG(*) entries,SUM(CASE WHEN race_key IS NULL OR horse_no IS NULL THEN 1 ELSE 0 END) missing_key,SUM(CASE WHEN horse_id IS NULL OR horse_id='' THEN 1 ELSE 0 END) missing_horse_id FROM history.entries WHERE __migration_source_snapshot_id=31",
        "entry_duplicates": "SELECT COUNT_BIG(*) duplicate_keys FROM (SELECT race_key,horse_no FROM history.entries WHERE __migration_source_snapshot_id=31 GROUP BY race_key,horse_no HAVING COUNT_BIG(*)>1) d",
        "label_duplicates": "SELECT COUNT_BIG(*) duplicate_keys FROM (SELECT race_key,horse_no FROM history.labels WHERE __migration_source_snapshot_id=31 GROUP BY race_key,horse_no HAVING COUNT_BIG(*)>1) d",
        "feature_status": "SELECT horizon,feature_status,COUNT_BIG(*) entries,SUM(CASE WHEN TRY_CONVERT(datetimeoffset,o1_announced_at)>TRY_CONVERT(datetimeoffset,market_cutoff_at) OR TRY_CONVERT(datetimeoffset,o2_announced_at)>TRY_CONVERT(datetimeoffset,market_cutoff_at) THEN 1 ELSE 0 END) announcements_after_cutoff,SUM(CASE WHEN source_o1_sha256 IS NULL THEN 1 ELSE 0 END) missing_o1_source,SUM(CASE WHEN source_o2_sha256 IS NULL THEN 1 ELSE 0 END) missing_o2_source FROM prediction.features_asof WHERE __migration_source_snapshot_id=31 GROUP BY horizon,feature_status ORDER BY horizon,feature_status",
        "feature_duplicates": "SELECT COUNT_BIG(*) duplicate_keys FROM (SELECT race_key,horse_no,horizon FROM prediction.features_asof WHERE __migration_source_snapshot_id=31 GROUP BY race_key,horse_no,horizon HAVING COUNT_BIG(*)>1) d",
        "odds_duplicates": "SELECT COUNT_BIG(*) duplicate_keys FROM (SELECT race_key,horizon,market FROM market.odds_asof_index WHERE __migration_source_snapshot_id=31 GROUP BY race_key,horizon,market HAVING COUNT_BIG(*)>1) d",
        "payout_status": "SELECT market,slot_status,COUNT_BIG(*) rows,SUM(CASE WHEN payout_yen IS NULL THEN 1 ELSE 0 END) null_payout FROM history.payouts WHERE __migration_source_snapshot_id=31 GROUP BY market,slot_status ORDER BY market,slot_status",
    },
    "temporal": {
        "odds_typed_times": "SELECT horizon,market,selection_status,COUNT_BIG(*) observations,SUM(CASE WHEN TRY_CONVERT(datetimeoffset,announced_at)>TRY_CONVERT(datetimeoffset,cutoff_at) THEN 1 ELSE 0 END) announcement_after_cutoff,SUM(CASE WHEN announced_at IS NOT NULL AND TRY_CONVERT(datetimeoffset,announced_at) IS NULL THEN 1 ELSE 0 END) invalid_announced_time,SUM(CASE WHEN TRY_CONVERT(datetimeoffset,cutoff_at) IS NULL THEN 1 ELSE 0 END) invalid_cutoff,MIN(TRY_CONVERT(datetimeoffset,cutoff_at)) first_cutoff,MAX(TRY_CONVERT(datetimeoffset,cutoff_at)) last_cutoff FROM market.odds_asof_index WHERE __migration_source_snapshot_id=31 GROUP BY horizon,market,selection_status ORDER BY horizon,market,selection_status",
        "feature_samples_by_horizon": "SELECT TOP (2) race_key,horse_no,horizon,features_json,masked_feature_names_json,feature_status FROM prediction.features_asof WHERE __migration_source_snapshot_id=31 AND horizon='T10'",
        "latest_history_races": "SELECT race_key,race_date,status,feature_eligibility FROM history.races WHERE __migration_source_snapshot_id=31 AND race_date>='2026-09-27' ORDER BY race_date,race_key",
    },
    "normalized_times": {
        "odds_normalized_times": "SELECT horizon,market,selection_status,COUNT_BIG(*) observations,SUM(CASE WHEN TRY_CONVERT(datetimeoffset,CASE WHEN LEN(announced_at)=22 AND SUBSTRING(announced_at,17,1) IN ('+','-') THEN STUFF(announced_at,17,0,':00') ELSE announced_at END)>TRY_CONVERT(datetimeoffset,cutoff_at) THEN 1 ELSE 0 END) announcement_after_cutoff,SUM(CASE WHEN announced_at IS NOT NULL AND TRY_CONVERT(datetimeoffset,CASE WHEN LEN(announced_at)=22 AND SUBSTRING(announced_at,17,1) IN ('+','-') THEN STUFF(announced_at,17,0,':00') ELSE announced_at END) IS NULL THEN 1 ELSE 0 END) invalid_announced_time,SUM(CASE WHEN TRY_CONVERT(datetimeoffset,cutoff_at) IS NULL THEN 1 ELSE 0 END) invalid_cutoff FROM market.odds_asof_index WHERE __migration_source_snapshot_id=31 GROUP BY horizon,market,selection_status ORDER BY horizon,market,selection_status",
    },
    "latest_scope": {
        "adopted_sources": "SELECT d.source_key,c.source_snapshot_id,s.status,s.captured_at_utc FROM ops.current_source_snapshot c JOIN ops.source_database d ON d.source_database_id=c.source_database_id JOIN ops.source_snapshot s ON s.source_snapshot_id=c.source_snapshot_id WHERE d.source_key IN ('analysis-current','prediction-full-20261008','nas-master-20261005','jv-results-2026') ORDER BY d.source_key",
        "api_recent_races": "SELECT r.race_id,r.race_date,r.course,r.race_no,CASE WHEN rr.race_id IS NULL THEN 0 ELSE 1 END has_result,(SELECT COUNT_BIG(*) FROM api_runtime.result_entries e WHERE e.__hash_race_id=r.__hash_race_id AND e.race_id=r.race_id) result_entries,(SELECT COUNT_BIG(*) FROM api_runtime.payouts p WHERE p.__hash_race_id=r.__hash_race_id AND p.race_id=r.race_id) payout_rows FROM api_runtime.races r LEFT JOIN api_runtime.race_results rr ON rr.__hash_race_id=r.__hash_race_id AND rr.race_id=r.race_id WHERE r.race_date>='2026-10-03' ORDER BY r.race_date,r.course,r.race_no",
        "migrated_recent_races": "SELECT race_date,course,COUNT_BIG(*) races FROM live.races WHERE __migration_source_snapshot_id=34 AND race_date>='2026-10-03' GROUP BY race_date,course ORDER BY race_date,course",
        "history_recent_races": "SELECT race_date,status,feature_eligibility,COUNT_BIG(*) races FROM history.races WHERE __migration_source_snapshot_id=31 AND race_date>='2026-09-27' GROUP BY race_date,status,feature_eligibility ORDER BY race_date,status",
        "netkeiba_recent_results": "SELECT race_date,course,COUNT_BIG(*) results FROM api_runtime.netkeiba_race_results WHERE race_date>='2026-10-03' GROUP BY race_date,course ORDER BY race_date,course",
        "year_original_latest": "SELECT record_type,COUNT_BIG(*) records,MAX(race_key) latest_race_key FROM raw.year_raw_records WHERE __migration_source_snapshot_id=27 GROUP BY record_type ORDER BY record_type",
        "master_catalog_latest": "SELECT scope,record_type,MIN(period) first_period,MAX(period) last_period,COUNT_BIG(*) coverage_rows FROM raw.master_coverage WHERE scope='local_catalog_race_key' GROUP BY scope,record_type",
    },
}


def main() -> int:
    """指定phaseのSELECTを順に実行し、各完了時と失敗時に証跡を保存する。

    Returns:
        全照会の成功は0、失敗は1。

    Notes:
        秘密値と例外本文は保存しない。SQLは固定されたSELECTだけを実行する。
        全DBのトランザクションsnapshotではなく、照会ごとの観測結果を記録する。
    """
    phase = sys.argv[1]
    queries = QUERIES[phase]
    output = Path(__file__).with_name(f"{phase}.json")
    report = {"phase": phase, "started_at_utc": datetime.now(UTC).isoformat(), "queries": {}}
    connection = None
    name = "connection"
    try:
        connection = runtime.connect(runtime.secrets(), role="reader")
        connection.timeout = 90
        for name, sql in queries.items():
            started = time.monotonic()
            cursor = connection.cursor()
            try:
                cursor.execute(sql)
                columns = [column[0] for column in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                report["queries"][name] = {"sql": sql, "observed_at_utc": datetime.now(UTC).isoformat(), "elapsed_seconds": round(time.monotonic() - started, 3), "rows": rows}
            finally:
                cursor.close()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            print(json.dumps({"query": name, "rows": len(rows), "elapsed_seconds": report["queries"][name]["elapsed_seconds"]}), flush=True)
        report["status"] = "succeeded"
        return 0
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__, failed_query=name if connection is not None else "connection")
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "failed_query": report["failed_query"]}), flush=True)
        return 1
    finally:
        if connection is not None:
            connection.close()
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
