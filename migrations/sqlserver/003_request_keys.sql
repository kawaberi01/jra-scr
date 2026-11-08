-- 概要: 任意Idempotency-Keyを要求fingerprintへ固定し、POST再試行の重複を防ぐ。
-- 作成日: 2026-10-15
-- 入力: 適用済みAPI運用schema。出力: 秘密や要求本文を含まないキー台帳。
-- 実行例: 管理CLIで明示適用。注意事項: 通常roleへDDL・既存移送表更新を許可しない。
IF DB_NAME() <> N'jra_unified' THROW 51000, 'Unexpected database', 1;
IF OBJECT_ID(N'api_runtime.request_keys') IS NULL
 CREATE TABLE api_runtime.request_keys (
  key_sha256 binary(32) NOT NULL PRIMARY KEY,
  request_fingerprint binary(32) NOT NULL,
  received_at_utc datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME()
 );
GRANT SELECT ON OBJECT::api_runtime.request_keys TO jra_api_reader;
GRANT SELECT,INSERT ON OBJECT::api_runtime.request_keys TO jra_api_writer;
