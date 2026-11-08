-- 概要: 通常writer公開前だけに使える運用schemaのrollback。元表を変更しない。
-- 作成日: 2026-10-15。入力: 本migrationの専用schema。出力: 追加schemaの削除。
-- 実行例: API停止・未公開確認後に管理者が明示実行。注意事項: ready以後は禁止。
IF DB_NAME() <> N'jra_unified' THROW 51000, 'Unexpected database', 1;
IF EXISTS(SELECT 1 FROM api_runtime.storage_state WHERE state_key=N'baseline' AND JSON_VALUE(value_json,'$.status')=N'ready')
 THROW 51000, 'Export SQL-only changes before rollback after writer publication', 1;
IF OBJECT_ID(N'api_runtime.request_keys') IS NOT NULL DROP TABLE api_runtime.request_keys;
IF OBJECT_ID(N'api_runtime.write_receipts') IS NOT NULL DROP TABLE api_runtime.write_receipts;
DROP TABLE [api_runtime].[stored_race_results];
DROP TABLE [api_runtime].[cache_entries];
DROP TABLE [api_runtime].[result_collection_jobs];
DROP TABLE [api_runtime].[jra_live_shadow_observations];
DROP TABLE [api_runtime].[jra_scout_entries];
DROP TABLE [api_runtime].[jra_scout_runs];
DROP TABLE [api_runtime].[daily_prediction_log_entries];
DROP TABLE [api_runtime].[daily_prediction_log_imports];
DROP TABLE [api_runtime].[bet_record_results];
DROP TABLE [api_runtime].[bet_record_tickets];
DROP TABLE [api_runtime].[bet_records];
DROP TABLE [api_runtime].[evaluation_ticket_results];
DROP TABLE [api_runtime].[evaluations];
DROP TABLE [api_runtime].[prediction_tickets];
DROP TABLE [api_runtime].[predictions];
DROP TABLE [api_runtime].[theory_versions];
DROP TABLE [api_runtime].[collection_errors];
DROP TABLE [api_runtime].[netkeiba_race_mappings];
DROP TABLE [api_runtime].[netkeiba_odds_entries];
DROP TABLE [api_runtime].[netkeiba_payouts];
DROP TABLE [api_runtime].[netkeiba_result_entries];
DROP TABLE [api_runtime].[netkeiba_race_results];
DROP TABLE [api_runtime].[payouts];
DROP TABLE [api_runtime].[result_entries];
DROP TABLE [api_runtime].[race_results];
DROP TABLE [api_runtime].[odds_entries];
DROP TABLE [api_runtime].[odds_snapshots];
DROP TABLE [api_runtime].[race_card_snapshot_runners];
DROP TABLE [api_runtime].[race_card_snapshots];
DROP TABLE [api_runtime].[runners];
DROP TABLE [api_runtime].[races];
DROP TABLE [api_runtime].[collection_runs];
DROP TABLE [api_runtime].[storage_state];
DROP SCHEMA [api_runtime];
