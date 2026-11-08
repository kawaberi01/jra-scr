# SQL Server API切替と復旧

作成日: 2026-10-15。対象: 087「既存SQL ServerへのAPI切替実装指示書」。

## 接続と正本

通常運用は `JRA_SRB_STORAGE_BACKEND=sqlserver` を使う。SQL Serverの `jra_unified.api_runtime` が業務データの読書き先になる。既存の `raw/history/market/live/prediction/ops` 移送表は取得時点の証跡として保持する。

2026-10-15 20:40:25 JSTにreadyと共通SQL設定を採用し、localhost:8000をSQL backendで起動した。日次収集も同じ設定ファイルを読む。最初の運用書込み確認は20:46:42 JSTの再生成可能なcache markerで、検証後に除去した。検証時点の通常業務受領は0件で、旧analysis/jobsのmain/WALは最終照合時から不変だった。

ローカルでは `data/storage/runtime.env` を共通設定として読む。別の場所を使う場合は `JRA_SRB_STORAGE_ENV_FILE` を指定する。プロセス環境変数がファイル設定に優先する。秘密ファイルはGit管理外の `data/` 内に置く。

| 設定名 | 内容 |
|---|---|
| `JRA_SRB_STORAGE_BACKEND` | `sqlserver` または明示的な旧 `sqlite` backend |
| `JRA_SRB_SQLSERVER_DATABASE` | `jra_unified` を明示 |
| `JRA_SRB_SQLSERVER_READER_CONNECTION_STRING` | reader専用接続。Databaseを含める |
| `JRA_SRB_SQLSERVER_WRITER_CONNECTION_STRING` | writer専用接続。Databaseを含める |
| `JRA_SRB_SQLSERVER_TIMEOUT_SECONDS` | SQL実行timeout、既定30秒 |
| `JRA_SRB_RESULTS_STORAGE` | SQL運用の既定値は `sqlserver`。明示exportは `jsonl` / `sqlite` |

SQLiteの `JRA_SRB_ANALYSIS_DB_PATH` / `JRA_SRB_JOBS_PATH` / `JRA_SRB_CACHE_PATH` にSQL接続文字列を入れない。SQLを選択した状態で `AnalysisSQLiteStore` を直接生成すると拒否する。SQL障害時のSQLite自動fallbackは設けていない。

通常loginは `jra_srb_api_reader` / `jra_srb_api_writer`。database roleは `jra_api_reader` / `jra_api_writer` で、運用対象表のSELECT、writerに必要なINSERT/UPDATE/DELETEだけを許可する。管理台帳は通常roleから更新できず、受領・要求キー台帳はSELECT/INSERTのみ。API接続時にも実DB名・db_owner/sysadminでないこと・baselineのready状態を検査する。`jra_owner` / `sa` は明示的な管理CLI以外で使用しない。

## API・worker・CLIの経路

| 経路 | SQL運用の接続先 |
|---|---|
| 出馬表・結果・払戻・オッズ・時点snapshotの保存/参照 | `SqlServerAnalysisStore` → `api_runtime` の業務29表 |
| 予想・買い目・購入・評価・日次ログ・scout・shadow | 同じStoreと業務29表。入力JSON・理論版・観測版を保持 |
| JRA/NAR/南関/provider系HTTPとMCP | 既存service/providerを維持し、cacheと南関の分析Storeを共通factoryへ接続 |
| TTL cache | `SqlServerTTLCache` → `cache_entries`。hit/expired/allow_expiredを維持 |
| 結果収集job・状態復旧 | `SqlServerJobRegistry` → `result_collection_jobs` |
| `/stored/results`・通常の結果収集保存 | `SqlServerRaceResultStorage` → `stored_race_results`。outputを名前空間として分離 |
| `jra-srb` CLI・日次odds worker | `build_analysis_store` / 共通結果factory |
| 履歴・近走・ラップ・V理論のDB参照 | `open_analysis_read` → SQL reader |
| `scripts` 内の通常参照・収集 | 共通factory / reader。直接呼ばれる `.workstate` の評価・監査補助2本も切替 |

HTTP 69入口とMCP 10 operation名、110モデル・817フィールドを切替前インベントリと照合する。追加した公開選択肢は `ResultStorageKind.sqlserver` と任意の `Idempotency-Key` header。既存path/query/bodyとモデル項目は維持する。

SQLは `mssql-python==1.15.0` で操作ごとに接続し、thread間で共有しない。既存の業務SQLは `sqlglot==30.23.0` で解析し、テーブルを運用schemaに限定する。`ON CONFLICT` は型を明示した `MERGE ... HOLDLOCK`、`LIMIT/OFFSET` は引数順を追跡したT-SQLへ変換する。元の明細順はseed時に保全したrowid、NULLの並び・UTC/JST比較は接続境界で扱う。

旧Storeにある親子制約は、SQL Storeで同一transactionの親行検査とロックによって維持する。移送表へFKを追加しない。複数表の業務更新はcommit/rollbackを共有し、外部HTTP取得中にはSQL transactionを保持しない。

## 明示migrationと最終差分

| 版 | 対象 |
|---|---|
| `001_api_runtime.sql` | 業務32表、`storage_state`、専用database role |
| `002_write_receipts.sql` | 不変の受領入力・受信時刻・再試行hash |
| `003_request_keys.sql` | 任意POST再試行キーと要求fingerprint |

必要な通常writer用領域だけを追加する。既存移送表はsnapshot/row hash/batch等の管理列を含め保持する。最初のseedは `ops.current_source_snapshot` と `source_key` でverifiedの採用版を解決し、SQL内のAPI業務30元表だけを対象にする。4.7億行の再取込は行わない。各業務行の元rowid・全列のNULL/バイト値を照合してからseedを確定する。

APIへの公開状態は、`seed_verified` → `final_sqlite_verified` → `ready` の順で進める。最終SQLiteはread-onlyで開き、既存のtyped-row-v1行SHAを使って変更行だけを判定する。旧writerを停止し、日次taskを無効化してから採取する。採取中とready採用直前にmain/WALのサイズ・mtimeを再確認する。

今回の最終照合ではanalysis・jobsの30表すべてで変更・追加・削除0件だった。基準は `analysis-current=34` / `jobs-current=3`。実行記録は `.workstate/jra-srb/sqlserver-api-cutover/` に置く。新しいAPI受領は運用表へ入り、移送用currentビューを上書きしない。

管理CLIの各actionは個別に実行する。接続先DB名、外部の管理者秘密ファイル、監査出力先を引数で明示する。`--help` で必要引数を確認する。秘密値をコマンド文字列・資料へ転記しない。

```powershell
uv run python tools/sqlserver_storage_admin.py --help
uv run python tools/audit_sqlserver_cutover.py --help
uv run python tools/verify_sqlserver_cutover_runtime.py --help
```

## 再試行と訂正

出馬表・オッズ・結果は、入力全体・取得時刻・source・観測時点を受領履歴へ保持する。完全に同じ受領入力の再試行は追記せず、同時刻でも内容が訂正された入力は別の受領版として保存する。受領記録と業務表の更新は同じtransactionに入る。

cache hitやTTLの応答メタデータだけが変わった場合は、新しい取得観測として重複追記しない。

新規予想・購入・jobをHTTPで再送する場合は、初回と同じ任意 `Idempotency-Key` を付ける。同じ要求は同じ業務IDに対応し、別path/query/bodyへのキーの再利用は409にする。キーを省略した購入などは、従来どおり新しい業務操作として扱う。予想の再送でも初回に保存した入力JSONを維持する。jobの実行開始はqueued状態からの原子的な取得で排他する。

## 残るSQLiteの用途

- 旧backendの4実装は明示SQLite運用・既存契約テスト用に保持する。SQL運用の通常factoryから業務writerとして選択しない。
- `--storage jsonl` / `--storage sqlite` とoutputを明示した結果exportは、従来のファイル出力を維持する。これらを通常SQL業務データの正本とはしない。
- 原本・解析済みオッズ・旧analysisファイルを明示指定する3つの過去学習/検証exportはread-only。HTTP/MCP/日次workerから呼ばれない。
- migrationの最終SQLite採取、復旧用export/復元候補作成は明示管理操作。
- 過去の `.workstate` 単発調査成果物は保持する。通常workerから直接呼ばれる評価/監査補助2本は共通readerへ改修済み。

cacheは再生成可能なため、旧TTL cacheの全件移送は行わない。SQLite/NAS原本・既存snapshotは削除しない。

`collect-results` は `--output` 必須の明示export用コマンドで、SQL運用中も既定JSONLを維持する。SQL保存には `--storage sqlserver` を明示する。jobでもoutputのみを明示した要求は従来どおりJSONLを出力する。

## 切戻し・復旧

通常writer開始前のschema rollbackは `001_rollback_before_writer.sql` を使う。ready採用後はこのrollbackを拒否する。

SQL writer開始後は、次の順で回収してから切り戻す。

1. 既知のAPI/collectorを停止し、日次taskを無効化する。SQL writerの停止時刻とPIDを記録する。
2. 管理CLIの `--action export-recovery --recovery-path <新規ファイル>` で運用32表・受領履歴・要求キー・管理状態を回収する。元SQLiteや既存SQL表へは書かない。
3. `restore_sqlserver_recovery.py` に保持した旧analysis/jobsと回収ファイル、未使用の出力ディレクトリを指定する。旧DBの制約・索引を保つ新規コピーへ全業務値を復元し、全値・件数・SQLite integrityを検証する。SQL結果保存の名前空間はJSONL候補へ分ける。
4. `verified-manifest.json` と出力を確認してから、切戻し先設定と正本を明示採用する。復元ツール自体は生成物を自動採用しない。cacheは再生成する。回収ファイルと元SQLは保持する。

```powershell
uv run python tools/restore_sqlserver_recovery.py --help
```

通常運用は既存構成どおり単一API processとする。別processが実行中のjobを保持したまま、追加API processで起動時回復を実行しない。

## 検証記録

静的な入口監査、全体回帰テスト、同一DB内の隔離schemaによるSQL契約検証を分けて記録する。SQL検証ではJRA/NAR、時点比較、NULL、取消、券種と組合せ、購入精算、cache stale、job再起動、並行再試行、最小権限、回収・復元候補を確認する。検証schemaは終了時に削除する。

稼働後はloopbackだけを対象に `verify_sqlserver_cutover_runtime.py` で旧read-only SQLiteとSQL Store、保存済みHTTP応答のhashを比較する。この検証は外部providerへ通信せず、業務データへ書き込まない。

切替時の記録: 全体回帰389件成功、SQL実接続39件とSQL境界unit11件成功、最終影響範囲の回帰98件成功。稼働比較はStore25件・HTTP24件が一致し、公開69 operationを確認した。MCPも実接続で10ツールと正規化呼出しを確認した。Pydanticの既存deprecation warningが1件ある。

最終監査では元81表のobject ID・メタデータ件数、1,440列・286索引、20ビュー定義、33採用sourceが不変だった。現在は116表で、追加した運用35表だけが増えている。検証schemaの残存は0。旧SQLiteのmain/WALも最終同期時からサイズ・mtimeが一致した。

日次taskは2026-10-15 21:16:51 JSTにReadyへ復帰し、次回は10月16日09:00 JST。APIは21:18:50 JSTに最終起動し、その後の稼働比較とMCP確認も成功した。翌日の実収集結果は将来の運用確認事項とする。

要件別の判定・証跡・変更一覧は [完了監査](../../.workstate/jra-srb/sqlserver-api-cutover/completion-audit.md) を参照する。
