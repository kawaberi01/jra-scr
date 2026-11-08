/*
概要: 研究readerが検証に必要な既存5オブジェクトの定義を参照できるようにする。
作成日: 2026-10-16
入力: jra_unifiedへの管理接続。既存データベースユーザーjra_reader。
出力: 対象5オブジェクトへのVIEW DEFINITION許可。実行失敗時は全体rollback。
実行例: 対象5表への追加許可を利用者が承認した後、管理接続で本SQLを実行する。
注意事項: 未実行の承認用案。データ・schema・索引・API設定は変更しない。
*/
SET XACT_ABORT ON;
IF DB_NAME() <> N'jra_unified'
    THROW 51000, N'管理対象DBがjra_unifiedではありません。', 1;
IF DATABASE_PRINCIPAL_ID(N'jra_reader') IS NULL
    THROW 51001, N'既存のjra_readerが存在しません。作成せず停止します。', 1;

BEGIN TRY
    BEGIN TRANSACTION;
    GRANT VIEW DEFINITION ON OBJECT::[market].[parsed_observations] TO [jra_reader];
    GRANT VIEW DEFINITION ON OBJECT::[market].[parsed_entries] TO [jra_reader];
    GRANT VIEW DEFINITION ON OBJECT::[raw].[master_contents] TO [jra_reader];
    GRANT VIEW DEFINITION ON OBJECT::[api_runtime].[write_receipts] TO [jra_reader];
    GRANT VIEW DEFINITION ON OBJECT::[history].[race_identity_map] TO [jra_reader];
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
