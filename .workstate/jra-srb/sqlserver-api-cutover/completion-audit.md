# 087 SQL Server API切替 完了監査

作成日: 2026-10-15。対象: `D:/develop/jra-scr`、既存 `jra_unified`。

## 判定

全通常API/worker/CLIのDB経路をSQL backendへ切り替え、loopback APIを起動した。日次収集taskはReadyへ復帰した。通常のSQLite業務writerとSQL writerの恒久的な二重管理はない。明示ファイルexport、旧backend、原本を指定するread-only学習exportは目的を記録して保持した。

## 要件と証跡

| 087の要件 | 実施・確認 | 証跡 |
|---|---|---|
| 1・5.1 現物・既存変更確認 | 関連AGENTS、084〜087、既存DDL、全入口、作業前diff・processを確認。既存変更を保持 | [進捗](progress/002-進捗サマリ.md)、[初期SQL現物](sqlserver-inventory.json) |
| 3 全経路 | HTTP69/MCP10、Store/cache/job/result、履歴、CLI、通常scriptと直接呼ばれる補助2本を切替 | [全入口監査](api-storage-audit.json)、[経路一覧](../../../docs/jra/30_SQLServer_API切替と復旧.md) |
| 4.1 取得版・provider | verifiedの採用source_keyからseed。既存移送表・currentビューを上書きしない。JV解析済みオッズをAPI観測として混ぜない | [seed](seed.json)、[最終差分](final-sqlite.json)、[DB監査](final-database-audit.json) |
| 4.2 必要最小DDL | 運用32表＋管理3表だけを追加。起動時DDLなし | [001](apply-schema.json)、[002](apply-receipts.json)、[003](apply-request-keys.json) |
| 4.2 受領・訂正・再試行 | immutable受領、型付きMERGE、短いtransaction、任意Idempotency-Key、jobの原子的claim、予想入力版固定 | [SQL検証](sqlserver-integration.xml) |
| 4.3 設定・秘密・権限 | 共通runtime.env、明示DB名、reader/writer分離。APIにowner/sa/DDLなし | [通常書込み・権限](operational-writer.json)、[設定整理](private-settings-cleanup.json) |
| 5.6 最終同期・単一writer | 日次task停止、30表の差分0、main/WAL不変、ready公開、その後SQL通常writer確認 | [停止](writer-stop.json)、[差分](final-sqlite.json)、[公開](publish.json) |
| 6 公開契約・応答 | 110モデル817項目不変。旧SQLite/SQL Store25件・稼働HTTP24件一致。MCP10ツールを実接続確認 | [静的監査](api-storage-audit.json)、[稼働比較](runtime-compatibility.json)、[MCP](mcp-runtime.json) |
| 6 SQL権限・再試行・job・時点 | 最小権限、並行再送、原子性、親子制約、復旧、JRA/NAR、as_of等を隔離schemaで検証 | [SQL検証](sqlserver-integration.xml) |
| 6 worker・残存SQLite | helper出力・SQL集計一致。残存8接続の用途分類、通常経路の未対応0 | [worker](worker-reader-compatibility.json)、[集計](worker-aggregate-compatibility.json)、[静的監査](api-storage-audit.json) |
| 7 原本保全 | 元81表のID・件数/列/索引、20ビュー、33採用source不変。旧SQLite/NASを削除せず、4.7億行を再投入しない | [DB監査](final-database-audit.json) |
| 8 運用再開・変更一覧・復旧 | API起動、日次task復帰、変更一覧と回収/復元手順 | [起動](api-process.json)、[task](scheduler-resumed.json)、[変更一覧](change-manifest.json) |

## DB変更の範囲

- 接続先: `127.0.0.1,11446`、database: `jra_unified`。既存コンテナを起動し、再作成・SQL Server設定変更は行わなかった。
- 001: 業務29表、jobs/cache/stored resultsの3表、storage_stateを追加。対象32表の全名称と適用SHAは `apply-schema.json`。
- 002: write_receipts、003: request_keysを追加。適用版・時刻・SHAを個別のJSONへ保存した。
- 追加後: 全116表・20ビュー、うちapi_runtimeが35表。検証用api_verify schema残存0。
- 元81表の1,440列・286索引、object IDとメタデータ行数が一致した。20ビュー定義も一致した。readerにはVIEW DEFINITIONがないため、定義だけは管理接続でSELECTした。見えなかった最初の監査は `final-database-audit-reader.json` に保持した。
- 33採用sourceは不変。seed対象はanalysis-currentとjobs-currentで、過去snapshotを無条件に混ぜていない。
- 1,755,523行をSQL内から運用表へseedして全値・rowidを照合した。最終SQLite差分は30表とも0件。
- 旧Storeの親子制約は同一transaction内の親行検査とロックで維持する。移送表へのFK追加は行わない。

## 時刻と通常writer

時刻はJST。各JSONにはUTCの実測値を保持する。

| 操作 | 2026-10-15の時刻 |
|---|---|
| 旧日次task停止 | 20:06:53 |
| 最終SQLite照合完了 | 20:07:54 |
| ready・共通設定公開 | 20:40:25 |
| 最初の通常SQL書込み確認 | 20:46:42（TTL cache marker、検証後除去） |
| 日次taskをReadyへ復帰 | 21:16:51 |
| 最終API起動 | 21:18:50 |

通常業務の架空データは投入していない。最終DB監査時点で業務受領・要求キーは0件。旧analysis/jobsのmain/WALは最終照合時からサイズ・mtimeが一致した。日次taskの次回実行は2026-10-16 09:00 JST。もともとDisabledだった週次2件は維持した。

## 検証結果と確認範囲

- 全体回帰: 389成功・38skip（当時のSQL opt-in37件と既存skip1件）。[記録](regression.xml)
- 後続のSQL実接続39件＋境界unit11件: 50成功。[記録](sqlserver-integration.xml)
- 最終の影響範囲回帰: 98成功。[記録](final-affected-regression.xml)
- 最終起動後のStore25件・HTTP24件が旧SQLiteと一致し、公開operation数69を確認した。
- MCPのSDK handshake、10ツール一覧、正規化operationが成功した。providerを呼ぶ全operationの再取得試験は行っていない。
- SQL実接続試験は同一DB内の隔離schemaを使い、終了時に除去した。回収・旧SQLiteの別コピーへの復元候補作成と制約保全も確認した。
- 既存のPydantic deprecation warningが1件ある。翌日の実収集は将来の運用確認で、現時点で成功したとは扱わない。
- 新規Python14ファイルのファイルヘッダー・クラス/関数説明に不足なし。差分の空白検査に成功した。

## 設定・残存SQLite・復旧

- backendは `JRA_SRB_STORAGE_BACKEND=sqlserver`、DBは `JRA_SRB_SQLSERVER_DATABASE` で明示する。reader/writer接続文字列とtimeoutを専用設定名で管理する。
- 通常loginは `jra_srb_api_reader` / `jra_srb_api_writer`、database roleは `jra_api_reader` / `jra_api_writer`。db_owner/sysadmin/CREATE TABLEなし。
- `data/storage/runtime.env` はGit管理外。秘密値を記録しない。公開済み設定と一致を確認した一時ファイルは除去した。
- 通常のSQL障害時にSQLiteへ自動fallbackしない。旧backendは明示的に選んだ場合だけ使用する。
- `collect-results` はoutput必須の明示exportのため既定JSONLを維持する。明示sqlite exportと、元ファイルを指定するread-only学習export3本も保持する。これらは通常業務正本ではない。
- SQL writer開始後の切戻しではwriterを停止し、`export-recovery` でSQL-only更新を回収する。`restore_sqlserver_recovery.py` で元DBを保持した新規コピーへ復元・照合し、復元候補を確認してから採用する。ready後のDDL rollbackは拒否する。
- 運用は既存構成に合わせて単一API process。複数API processの同時起動を新たに導入していない。

## 変更の扱い

詳細は `change-manifest.json`。作業前から存在した `tests/test_jra_odds_timeline.py` の変更・旧APIログ・無関係な未追跡成果物は今回の成果として数えない。既存timeline本体と日次PSでは今回の変更は説明ヘッダーのみ。Git commit、Notion書込みは行っていない。
