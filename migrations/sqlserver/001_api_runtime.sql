-- 概要: API用の通常writer領域だけを追加する。既存移送表は変更しない。
-- 作成日: 2026-10-15。入力: 確認済み業務列契約。出力: api_runtime schema。
-- 実行例: 管理CLIから明示apply。注意事項: jra_unified限定、seedと採用確認が別途必要。
IF DB_NAME() <> N'jra_unified' THROW 51000, 'Unexpected database', 1;
SET XACT_ABORT ON;
IF SCHEMA_ID(N'api_runtime') IS NULL EXEC(N'CREATE SCHEMA [api_runtime] AUTHORIZATION [dbo]');
GO
IF OBJECT_ID(N'api_runtime.storage_state') IS NULL CREATE TABLE [api_runtime].[storage_state] (
 [state_key] nvarchar(128) NOT NULL PRIMARY KEY, [value_json] nvarchar(max) NOT NULL,
 [updated_at_utc] datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME());
GO
IF DATABASE_PRINCIPAL_ID(N'jra_api_reader') IS NULL CREATE ROLE [jra_api_reader];
IF DATABASE_PRINCIPAL_ID(N'jra_api_writer') IS NULL CREATE ROLE [jra_api_writer];
GRANT SELECT ON OBJECT::[api_runtime].[storage_state] TO [jra_api_reader];
GRANT SELECT ON OBJECT::[api_runtime].[storage_state] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.collection_runs') IS NULL BEGIN
CREATE TABLE [api_runtime].[collection_runs] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [run_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [from_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [to_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [courses_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [include_card] bigint NOT NULL,
 [include_odds] bigint NOT NULL,
 [include_results] bigint NOT NULL,
 [odds_timing] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [finished_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_run_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [run_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_collection_runs_0] ON [api_runtime].[collection_runs] ([__hash_run_id]) WHERE [run_id] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[collection_runs] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[collection_runs] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.races') IS NULL BEGIN
CREATE TABLE [api_runtime].[races] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [meeting_no] bigint NULL,
 [meeting_day] bigint NULL,
 [race_no] bigint NOT NULL,
 [race_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_grade] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [start_time] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [surface] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [surface_label] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [distance] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weather] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weather_label] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [track_condition] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [track_condition_label] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [fetched_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_race_date] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_date])) PERSISTED,
 [__hash_course] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [course])) PERSISTED
);
CREATE UNIQUE INDEX [UX_races_0] ON [api_runtime].[races] ([__hash_race_id]) WHERE [race_id] IS NOT NULL;
CREATE INDEX [IX_races_0] ON [api_runtime].[races] ([__hash_race_date], [__hash_course], [race_no]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[races] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[races] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.runners') IS NULL BEGIN
CREATE TABLE [api_runtime].[runners] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [horse_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [frame_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [sex_age] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weight_carried] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [jockey] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [trainer] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_weight] bigint NULL,
 [horse_weight_diff] bigint NULL,
 [card_odds] float(53) NULL,
 [card_popularity] bigint NULL,
 [status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL DEFAULT 'active',
 [status_source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_horse_no] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [horse_no])) PERSISTED
);
CREATE UNIQUE INDEX [UX_runners_0] ON [api_runtime].[runners] ([__hash_race_id], [__hash_horse_no]) WHERE [race_id] IS NOT NULL AND [horse_no] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[runners] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[runners] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.race_card_snapshots') IS NULL BEGIN
CREATE TABLE [api_runtime].[race_card_snapshots] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [card_snapshot_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [meeting_no] bigint NULL,
 [meeting_day] bigint NULL,
 [race_no] bigint NOT NULL,
 [race_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [start_time] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [surface] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [surface_label] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [distance] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weather] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weather_label] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [track_condition] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [track_condition_label] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [source_kind] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [runner_set_status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [runner_set_reason] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [runner_count] bigint NOT NULL,
 [fetched_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_card_snapshot_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [card_snapshot_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_race_card_snapshots_0] ON [api_runtime].[race_card_snapshots] ([__hash_card_snapshot_id]) WHERE [card_snapshot_id] IS NOT NULL;
CREATE INDEX [IX_race_card_snapshots_0] ON [api_runtime].[race_card_snapshots] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[race_card_snapshots] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[race_card_snapshots] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.race_card_snapshot_runners') IS NULL BEGIN
CREATE TABLE [api_runtime].[race_card_snapshot_runners] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [card_snapshot_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [horse_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [frame_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [sex_age] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weight_carried] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [jockey] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [trainer] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_weight] bigint NULL,
 [horse_weight_diff] bigint NULL,
 [card_odds] float(53) NULL,
 [card_popularity] bigint NULL,
 [status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [status_source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_card_snapshot_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [card_snapshot_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_horse_no] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [horse_no])) PERSISTED
);
CREATE UNIQUE INDEX [UX_race_card_snapshot_runners_0] ON [api_runtime].[race_card_snapshot_runners] ([__hash_card_snapshot_id], [__hash_horse_no]) WHERE [card_snapshot_id] IS NOT NULL AND [horse_no] IS NOT NULL;
CREATE INDEX [IX_race_card_snapshot_runners_0] ON [api_runtime].[race_card_snapshot_runners] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[race_card_snapshot_runners] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[race_card_snapshot_runners] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.odds_snapshots') IS NULL BEGIN
CREATE TABLE [api_runtime].[odds_snapshots] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [snapshot_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [odds_timing] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [fetched_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_snapshot_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [snapshot_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_bet_type] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_type])) PERSISTED,
 [__hash_odds_timing] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [odds_timing])) PERSISTED,
 [__hash_fetched_at] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [fetched_at])) PERSISTED
);
CREATE UNIQUE INDEX [UX_odds_snapshots_0] ON [api_runtime].[odds_snapshots] ([__hash_snapshot_id]) WHERE [snapshot_id] IS NOT NULL;
CREATE INDEX [IX_odds_snapshots_0] ON [api_runtime].[odds_snapshots] ([__hash_race_id], [__hash_bet_type], [__hash_odds_timing], [__hash_fetched_at]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[odds_snapshots] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[odds_snapshots] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.odds_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[odds_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [snapshot_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [combination] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [combination_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [odds] float(53) NULL,
 [odds_min] float(53) NULL,
 [odds_max] float(53) NULL,
 [popularity] bigint NULL,
 [__hash_snapshot_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [snapshot_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_bet_type] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_type])) PERSISTED
);
CREATE INDEX [IX_odds_entries_0] ON [api_runtime].[odds_entries] ([__hash_race_id], [__hash_bet_type]);
CREATE INDEX [IX_odds_entries_1] ON [api_runtime].[odds_entries] ([__hash_bet_type], [odds]);
CREATE INDEX [IX_odds_entries_2] ON [api_runtime].[odds_entries] ([__hash_bet_type], [popularity]);
CREATE INDEX [IX_odds_entries_3] ON [api_runtime].[odds_entries] ([__hash_snapshot_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[odds_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[odds_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.race_results') IS NULL BEGIN
CREATE TABLE [api_runtime].[race_results] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [fetched_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_race_results_0] ON [api_runtime].[race_results] ([__hash_race_id]) WHERE [race_id] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[race_results] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[race_results] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.result_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[result_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [rank] bigint NULL,
 [horse_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [jockey] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [finish_time] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_horse_no] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [horse_no])) PERSISTED
);
CREATE UNIQUE INDEX [UX_result_entries_0] ON [api_runtime].[result_entries] ([__hash_race_id], [rank], [__hash_horse_no]) WHERE [race_id] IS NOT NULL AND [rank] IS NOT NULL AND [horse_no] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[result_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[result_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.payouts') IS NULL BEGIN
CREATE TABLE [api_runtime].[payouts] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [combination] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [payout] bigint NULL,
 [popularity] bigint NULL,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_bet_type] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_type])) PERSISTED
);
CREATE INDEX [IX_payouts_0] ON [api_runtime].[payouts] ([__hash_race_id], [__hash_bet_type]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[payouts] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[payouts] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.netkeiba_race_results') IS NULL BEGIN
CREATE TABLE [api_runtime].[netkeiba_race_results] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [netkeiba_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [jra_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_no] bigint NULL,
 [race_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [surface] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [distance] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [direction] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weather] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [track_condition] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_laps_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [fetched_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [raw_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_netkeiba_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [netkeiba_race_id])) PERSISTED,
 [__hash_jra_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [jra_race_id])) PERSISTED,
 [__hash_race_date] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_date])) PERSISTED,
 [__hash_course] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [course])) PERSISTED
);
CREATE UNIQUE INDEX [UX_netkeiba_race_results_0] ON [api_runtime].[netkeiba_race_results] ([__hash_netkeiba_race_id]) WHERE [netkeiba_race_id] IS NOT NULL;
CREATE INDEX [IX_netkeiba_race_results_0] ON [api_runtime].[netkeiba_race_results] ([__hash_jra_race_id]);
CREATE INDEX [IX_netkeiba_race_results_1] ON [api_runtime].[netkeiba_race_results] ([__hash_race_date], [__hash_course], [race_no]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[netkeiba_race_results] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[netkeiba_race_results] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.netkeiba_result_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[netkeiba_result_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [netkeiba_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [jra_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [rank] bigint NULL,
 [frame_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_no] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_name] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [sex_age] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [weight_carried] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [jockey] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [trainer] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [horse_weight] bigint NULL,
 [horse_weight_diff] bigint NULL,
 [finish_time] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [margin] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [corner_order] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [final_3f] float(53) NULL,
 [win_odds] float(53) NULL,
 [popularity] bigint NULL,
 [__hash_netkeiba_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [netkeiba_race_id])) PERSISTED,
 [__hash_jra_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [jra_race_id])) PERSISTED,
 [__hash_horse_no] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [horse_no])) PERSISTED
);
CREATE UNIQUE INDEX [UX_netkeiba_result_entries_0] ON [api_runtime].[netkeiba_result_entries] ([__hash_netkeiba_race_id], [rank], [__hash_horse_no]) WHERE [netkeiba_race_id] IS NOT NULL AND [rank] IS NOT NULL AND [horse_no] IS NOT NULL;
CREATE INDEX [IX_netkeiba_result_entries_0] ON [api_runtime].[netkeiba_result_entries] ([__hash_jra_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[netkeiba_result_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[netkeiba_result_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.netkeiba_payouts') IS NULL BEGIN
CREATE TABLE [api_runtime].[netkeiba_payouts] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [netkeiba_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [jra_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [combination] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [payout] bigint NULL,
 [popularity] bigint NULL,
 [__hash_netkeiba_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [netkeiba_race_id])) PERSISTED,
 [__hash_jra_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [jra_race_id])) PERSISTED,
 [__hash_bet_type] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_type])) PERSISTED
);
CREATE INDEX [IX_netkeiba_payouts_0] ON [api_runtime].[netkeiba_payouts] ([__hash_netkeiba_race_id], [__hash_bet_type]);
CREATE INDEX [IX_netkeiba_payouts_1] ON [api_runtime].[netkeiba_payouts] ([__hash_jra_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[netkeiba_payouts] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[netkeiba_payouts] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.netkeiba_odds_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[netkeiba_odds_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [netkeiba_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [jra_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [combination] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [combination_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [odds] float(53) NULL,
 [odds_min] float(53) NULL,
 [odds_max] float(53) NULL,
 [popularity] bigint NULL,
 [fetched_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_netkeiba_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [netkeiba_race_id])) PERSISTED,
 [__hash_jra_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [jra_race_id])) PERSISTED,
 [__hash_bet_type] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_type])) PERSISTED,
 [__hash_combination] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [combination])) PERSISTED
);
CREATE UNIQUE INDEX [UX_netkeiba_odds_entries_0] ON [api_runtime].[netkeiba_odds_entries] ([__hash_netkeiba_race_id], [__hash_bet_type], [__hash_combination]) WHERE [netkeiba_race_id] IS NOT NULL AND [bet_type] IS NOT NULL AND [combination] IS NOT NULL;
CREATE INDEX [IX_netkeiba_odds_entries_0] ON [api_runtime].[netkeiba_odds_entries] ([__hash_jra_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[netkeiba_odds_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[netkeiba_odds_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.netkeiba_race_mappings') IS NULL BEGIN
CREATE TABLE [api_runtime].[netkeiba_race_mappings] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [jra_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [netkeiba_race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_no] bigint NULL,
 [mapping_status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [mapping_note] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [updated_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_jra_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [jra_race_id])) PERSISTED,
 [__hash_netkeiba_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [netkeiba_race_id])) PERSISTED,
 [__hash_race_date] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_date])) PERSISTED,
 [__hash_course] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [course])) PERSISTED,
 [__hash_mapping_status] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [mapping_status])) PERSISTED
);
CREATE UNIQUE INDEX [UX_netkeiba_race_mappings_0] ON [api_runtime].[netkeiba_race_mappings] ([__hash_jra_race_id]) WHERE [jra_race_id] IS NOT NULL;
CREATE INDEX [IX_netkeiba_race_mappings_0] ON [api_runtime].[netkeiba_race_mappings] ([__hash_race_date], [__hash_course], [race_no]);
CREATE INDEX [IX_netkeiba_race_mappings_1] ON [api_runtime].[netkeiba_race_mappings] ([__hash_mapping_status]);
CREATE INDEX [IX_netkeiba_race_mappings_2] ON [api_runtime].[netkeiba_race_mappings] ([__hash_netkeiba_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[netkeiba_race_mappings] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[netkeiba_race_mappings] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.collection_errors') IS NULL BEGIN
CREATE TABLE [api_runtime].[collection_errors] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [error_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [run_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_no] bigint NULL,
 [stage] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [error_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [error_message] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_error_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [error_id])) PERSISTED,
 [__hash_run_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [run_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_collection_errors_0] ON [api_runtime].[collection_errors] ([__hash_error_id]) WHERE [error_id] IS NOT NULL;
CREATE INDEX [IX_collection_errors_0] ON [api_runtime].[collection_errors] ([__hash_run_id]);
CREATE INDEX [IX_collection_errors_1] ON [api_runtime].[collection_errors] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[collection_errors] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[collection_errors] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.theory_versions') IS NULL BEGIN
CREATE TABLE [api_runtime].[theory_versions] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [theory_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [parent_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [theory_yaml] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [notes] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [promoted_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_theory_version] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [theory_version])) PERSISTED
);
CREATE UNIQUE INDEX [UX_theory_versions_0] ON [api_runtime].[theory_versions] ([__hash_theory_version]) WHERE [theory_version] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[theory_versions] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[theory_versions] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.predictions') IS NULL BEGIN
CREATE TABLE [api_runtime].[predictions] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [prediction_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [theory_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [mode] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [budget] bigint NULL,
 [pre_race_snapshot_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [prediction_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_prediction_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [prediction_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_predictions_0] ON [api_runtime].[predictions] ([__hash_prediction_id]) WHERE [prediction_id] IS NOT NULL;
CREATE INDEX [IX_predictions_0] ON [api_runtime].[predictions] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[predictions] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[predictions] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.prediction_tickets') IS NULL BEGIN
CREATE TABLE [api_runtime].[prediction_tickets] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [ticket_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [prediction_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [bucket] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [selection] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [selection_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [amount] bigint NOT NULL,
 [reason] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_ticket_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [ticket_id])) PERSISTED,
 [__hash_prediction_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [prediction_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_prediction_tickets_0] ON [api_runtime].[prediction_tickets] ([__hash_ticket_id]) WHERE [ticket_id] IS NOT NULL;
CREATE INDEX [IX_prediction_tickets_0] ON [api_runtime].[prediction_tickets] ([__hash_prediction_id]);
CREATE INDEX [IX_prediction_tickets_1] ON [api_runtime].[prediction_tickets] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[prediction_tickets] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[prediction_tickets] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.evaluations') IS NULL BEGIN
CREATE TABLE [api_runtime].[evaluations] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [evaluation_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [prediction_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [theory_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [total_bet] bigint NOT NULL,
 [total_payout] bigint NOT NULL,
 [return_rate] float(53) NOT NULL,
 [hit] bigint NOT NULL,
 [gami] bigint NOT NULL,
 [axis_in_top3] bigint NULL,
 [middle_hole_in_top3] bigint NULL,
 [firework_hit] bigint NULL,
 [max_odds_selected] float(53) NULL,
 [evaluation_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_evaluation_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [evaluation_id])) PERSISTED,
 [__hash_prediction_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [prediction_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_evaluations_0] ON [api_runtime].[evaluations] ([__hash_evaluation_id]) WHERE [evaluation_id] IS NOT NULL;
CREATE INDEX [IX_evaluations_0] ON [api_runtime].[evaluations] ([__hash_prediction_id]);
CREATE INDEX [IX_evaluations_1] ON [api_runtime].[evaluations] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[evaluations] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[evaluations] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.evaluation_ticket_results') IS NULL BEGIN
CREATE TABLE [api_runtime].[evaluation_ticket_results] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [ticket_result_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [evaluation_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [ticket_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bucket] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [selection] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [amount] bigint NOT NULL,
 [hit] bigint NOT NULL,
 [payout] bigint NOT NULL,
 [__hash_ticket_result_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [ticket_result_id])) PERSISTED,
 [__hash_evaluation_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [evaluation_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_evaluation_ticket_results_0] ON [api_runtime].[evaluation_ticket_results] ([__hash_ticket_result_id]) WHERE [ticket_result_id] IS NOT NULL;
CREATE INDEX [IX_evaluation_ticket_results_0] ON [api_runtime].[evaluation_ticket_results] ([__hash_evaluation_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[evaluation_ticket_results] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[evaluation_ticket_results] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.bet_records') IS NULL BEGIN
CREATE TABLE [api_runtime].[bet_records] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [bet_record_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [prediction_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [theory_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [decision_source] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [purchased_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [total_amount] bigint NOT NULL,
 [note] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [updated_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_bet_record_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_record_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_prediction_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [prediction_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_bet_records_0] ON [api_runtime].[bet_records] ([__hash_bet_record_id]) WHERE [bet_record_id] IS NOT NULL;
CREATE INDEX [IX_bet_records_0] ON [api_runtime].[bet_records] ([__hash_race_id]);
CREATE INDEX [IX_bet_records_1] ON [api_runtime].[bet_records] ([__hash_prediction_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[bet_records] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[bet_records] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.bet_record_tickets') IS NULL BEGIN
CREATE TABLE [api_runtime].[bet_record_tickets] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [bet_ticket_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_record_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [prediction_ticket_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bucket] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [selection] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [selection_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [amount] bigint NOT NULL,
 [odds_at_buy] float(53) NULL,
 [is_box_expanded] bigint NOT NULL,
 [reason] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_bet_ticket_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_ticket_id])) PERSISTED,
 [__hash_bet_record_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_record_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_bet_type] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_type])) PERSISTED,
 [__hash_selection] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [selection])) PERSISTED
);
CREATE UNIQUE INDEX [UX_bet_record_tickets_0] ON [api_runtime].[bet_record_tickets] ([__hash_bet_ticket_id]) WHERE [bet_ticket_id] IS NOT NULL;
CREATE INDEX [IX_bet_record_tickets_0] ON [api_runtime].[bet_record_tickets] ([__hash_bet_record_id]);
CREATE INDEX [IX_bet_record_tickets_1] ON [api_runtime].[bet_record_tickets] ([__hash_race_id], [__hash_bet_type], [__hash_selection]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[bet_record_tickets] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[bet_record_tickets] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.bet_record_results') IS NULL BEGIN
CREATE TABLE [api_runtime].[bet_record_results] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [bet_record_result_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [bet_record_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [total_bet] bigint NOT NULL,
 [total_payout] bigint NOT NULL,
 [return_rate] float(53) NOT NULL,
 [hit] bigint NOT NULL,
 [settled_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [result_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_bet_record_result_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_record_result_id])) PERSISTED,
 [__hash_bet_record_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [bet_record_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_bet_record_results_0] ON [api_runtime].[bet_record_results] ([__hash_bet_record_result_id]) WHERE [bet_record_result_id] IS NOT NULL;
CREATE UNIQUE INDEX [UX_bet_record_results_1] ON [api_runtime].[bet_record_results] ([__hash_bet_record_id]) WHERE [bet_record_id] IS NOT NULL;
CREATE INDEX [IX_bet_record_results_0] ON [api_runtime].[bet_record_results] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[bet_record_results] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[bet_record_results] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.daily_prediction_log_imports') IS NULL BEGIN
CREATE TABLE [api_runtime].[daily_prediction_log_imports] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [import_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [source_path] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [log_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [venue] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [imported_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_import_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [import_id])) PERSISTED,
 [__hash_source_path] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [source_path])) PERSISTED,
 [__hash_log_date] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [log_date])) PERSISTED
);
CREATE UNIQUE INDEX [UX_daily_prediction_log_imports_0] ON [api_runtime].[daily_prediction_log_imports] ([__hash_import_id]) WHERE [import_id] IS NOT NULL;
CREATE UNIQUE INDEX [UX_daily_prediction_log_imports_1] ON [api_runtime].[daily_prediction_log_imports] ([__hash_source_path], [__hash_log_date]) WHERE [source_path] IS NOT NULL AND [log_date] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[daily_prediction_log_imports] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[daily_prediction_log_imports] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.daily_prediction_log_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[daily_prediction_log_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [entry_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [import_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_no] bigint NULL,
 [entry_timestamp] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [entry_type] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [topic] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [prediction_mode] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [raw_markdown] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [payload_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_entry_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [entry_id])) PERSISTED,
 [__hash_import_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [import_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_race_date] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_date])) PERSISTED,
 [__hash_course] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [course])) PERSISTED
);
CREATE UNIQUE INDEX [UX_daily_prediction_log_entries_0] ON [api_runtime].[daily_prediction_log_entries] ([__hash_entry_id]) WHERE [entry_id] IS NOT NULL;
CREATE INDEX [IX_daily_prediction_log_entries_0] ON [api_runtime].[daily_prediction_log_entries] ([__hash_import_id]);
CREATE INDEX [IX_daily_prediction_log_entries_1] ON [api_runtime].[daily_prediction_log_entries] ([__hash_race_date], [__hash_course], [race_no]);
CREATE INDEX [IX_daily_prediction_log_entries_2] ON [api_runtime].[daily_prediction_log_entries] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[daily_prediction_log_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[daily_prediction_log_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.jra_scout_runs') IS NULL BEGIN
CREATE TABLE [api_runtime].[jra_scout_runs] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [run_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [observed_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [phase] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_count] bigint NOT NULL,
 [analyzed_count] bigint NOT NULL,
 [candidates_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [errors_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_run_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [run_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_jra_scout_runs_0] ON [api_runtime].[jra_scout_runs] ([__hash_run_id]) WHERE [run_id] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[jra_scout_runs] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[jra_scout_runs] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.jra_scout_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[jra_scout_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [run_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_no] bigint NOT NULL,
 [grade] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [entry_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_run_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [run_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_grade] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [grade])) PERSISTED
);
CREATE UNIQUE INDEX [UX_jra_scout_entries_0] ON [api_runtime].[jra_scout_entries] ([__hash_run_id], [__hash_race_id]) WHERE [run_id] IS NOT NULL AND [race_id] IS NOT NULL;
CREATE INDEX [IX_jra_scout_entries_0] ON [api_runtime].[jra_scout_entries] ([__hash_run_id], [__hash_grade]);
CREATE INDEX [IX_jra_scout_entries_1] ON [api_runtime].[jra_scout_entries] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[jra_scout_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[jra_scout_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.jra_live_shadow_observations') IS NULL BEGIN
CREATE TABLE [api_runtime].[jra_live_shadow_observations] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [observation_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [run_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_no] bigint NOT NULL,
 [observed_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [model_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [policy_version] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [decision_status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [ticket_status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [payload_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_observation_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [observation_id])) PERSISTED,
 [__hash_run_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [run_id])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_observed_at] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [observed_at])) PERSISTED
);
CREATE UNIQUE INDEX [UX_jra_live_shadow_observations_0] ON [api_runtime].[jra_live_shadow_observations] ([__hash_observation_id]) WHERE [observation_id] IS NOT NULL;
CREATE UNIQUE INDEX [UX_jra_live_shadow_observations_1] ON [api_runtime].[jra_live_shadow_observations] ([__hash_run_id], [__hash_race_id]) WHERE [run_id] IS NOT NULL AND [race_id] IS NOT NULL;
CREATE INDEX [IX_jra_live_shadow_observations_0] ON [api_runtime].[jra_live_shadow_observations] ([__hash_race_id], [__hash_observed_at]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[jra_live_shadow_observations] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[jra_live_shadow_observations] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.result_collection_jobs') IS NULL BEGIN
CREATE TABLE [api_runtime].[result_collection_jobs] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [job_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [status] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [from_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [to_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [courses_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [storage] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [output] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [retries] bigint NOT NULL,
 [created_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [started_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [finished_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [message] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [error] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [__hash_job_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [job_id])) PERSISTED
);
CREATE UNIQUE INDEX [UX_result_collection_jobs_0] ON [api_runtime].[result_collection_jobs] ([__hash_job_id]) WHERE [job_id] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[result_collection_jobs] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[result_collection_jobs] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.cache_entries') IS NULL BEGIN
CREATE TABLE [api_runtime].[cache_entries] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [cache_key] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [value_blob] varbinary(max) NOT NULL,
 [expires_at] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_cache_key] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [cache_key])) PERSISTED
);
CREATE UNIQUE INDEX [UX_cache_entries_0] ON [api_runtime].[cache_entries] ([__hash_cache_key]) WHERE [cache_key] IS NOT NULL;
END;
GRANT SELECT ON OBJECT::[api_runtime].[cache_entries] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[cache_entries] TO [jra_api_writer];
GO
IF OBJECT_ID(N'api_runtime.stored_race_results') IS NULL BEGIN
CREATE TABLE [api_runtime].[stored_race_results] (
 [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 [__seed_source_snapshot_id] bigint NULL,
 [storage_namespace] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_id] nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL,
 [race_date] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [course] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [race_no] bigint NOT NULL,
 [result_json] nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
 [__hash_storage_namespace] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [storage_namespace])) PERSISTED,
 [__hash_race_id] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_id])) PERSISTED,
 [__hash_race_date] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [race_date])) PERSISTED,
 [__hash_course] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [course])) PERSISTED
);
CREATE UNIQUE INDEX [UX_stored_race_results_0] ON [api_runtime].[stored_race_results] ([__hash_storage_namespace], [__hash_race_id]) WHERE [storage_namespace] IS NOT NULL AND [race_id] IS NOT NULL;
CREATE INDEX [IX_stored_race_results_0] ON [api_runtime].[stored_race_results] ([__hash_storage_namespace], [__hash_race_date], [__hash_course]);
CREATE INDEX [IX_stored_race_results_1] ON [api_runtime].[stored_race_results] ([__hash_race_id]);
END;
GRANT SELECT ON OBJECT::[api_runtime].[stored_race_results] TO [jra_api_reader];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[api_runtime].[stored_race_results] TO [jra_api_writer];
GO
