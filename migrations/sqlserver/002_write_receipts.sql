-- 概要: 再試行の重複防止と訂正入力版の保持に必要な受領履歴を追加する。
-- 作成日: 2026-10-15
-- 入力: 適用済み001のapi_runtime schema。出力: 不変の入力版・受信時刻・冪等キー。
-- 実行例: 管理CLIから明示適用。注意事項: 既存移送表・採用snapshotを変更しない。
IF DB_NAME() <> N'jra_unified' THROW 51000, 'Unexpected database', 1;
IF OBJECT_ID(N'api_runtime.write_receipts') IS NULL
BEGIN
 CREATE TABLE api_runtime.write_receipts (
  request_sha256 binary(32) NOT NULL PRIMARY KEY,
  operation nvarchar(64) NOT NULL,
  race_id nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL,
  payload_json nvarchar(max) NOT NULL,
  received_at_utc datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME(),
  race_sha256 AS CONVERT(binary(32),HASHBYTES('SHA2_256',race_id)) PERSISTED
 );
 CREATE INDEX IX_write_receipts_race ON api_runtime.write_receipts(race_sha256,received_at_utc);
END;
GRANT SELECT ON OBJECT::api_runtime.write_receipts TO jra_api_reader;
GRANT SELECT,INSERT ON OBJECT::api_runtime.write_receipts TO jra_api_writer;
