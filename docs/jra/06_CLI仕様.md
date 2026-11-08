# CLI仕様

この文書は `src/jra_srb/cli.py` に実装されている CLI の正本です。

## 呼び出し方

インストール後:

```powershell
uv run jra-srb --help
```

モジュール実行:

```powershell
uv run python -m jra_srb.cli --help
```

## 共通

- 文字列の日付は `YYYY-MM-DD`
- `--courses` は `nakayama,hanshin` のようなカンマ区切り
- `--db` の既定値は `data/db/analysis.sqlite`
- `--db` は旧SQLite backendのパス。SQL運用では `data/storage/runtime.env` または明示環境設定の接続を使い、`--db` をSQL接続文字列には読み替えない
- ローカル API 呼び出し系の `--base-url` 既定値は `http://127.0.0.1:8000`

通常の分析収集・検証・日次workerは共通backendへ接続する。設定と復旧は [SQL Server API切替と復旧](30_SQLServer_API切替と復旧.md) を参照する。

## コマンド一覧

### `collect-results`

JRA の過去結果を明示exportとして保存する。必須の `--output` を持つこのコマンドは、従来どおり既定でJSONLを出力する。`--storage sqlserver` を明示するとoutputをSQL保存の名前空間として使う。

主な引数:

- `--from-date`
- `--to-date`
- `--courses`
- `--output`
- `--storage jsonl|sqlite|sqlserver`
- `--retries`

例:

```powershell
uv run jra-srb collect-results --from-date 2026-03-22 --to-date 2026-03-22 --courses nakayama --output data/results.jsonl
```

### `collect-analysis`

選択backendの分析Storeにカード、オッズ、結果を収集する。

主な引数:

- `--from-date`
- `--to-date`
- `--courses`
- `--db`
- `--include-card`
- `--include-odds`
- `--include-results`
- `--bet-types`
- `--odds-timing`
- `--retries`
- `--min-interval-seconds`
- `--max-live-requests`
- `--skip-existing`

例:

```powershell
uv run jra-srb collect-analysis --from-date 2026-03-22 --to-date 2026-03-22 --courses nakayama --db data/db/analysis.sqlite --include-card --include-odds --include-results
```

### `collect-jra-odds-timeline`

指定開催日の出馬表・オッズを発走前の時点ごとに共通backendへ保存する。

- `--date YYYY-MM-DD`、`--courses all`、`--db`
- `--bet-types`、`--offset-minutes`、`--bet-type-offsets`
- `--poll-seconds`、`--min-interval-seconds`、`--max-lateness-seconds`
- `--max-live-requests`：出馬表・オッズの取得試行上限。失敗した試行も含む。省略時は当日の開催・券種・取得時点から有限の上限を自動算出する。
- `--dry-run`：予定を表示する。出馬表・オッズの取得保存はしない。
- `--refresh-existing`：保存済み時点も新しい世代として追記する。

日次設定では単勝・馬連・ワイドを30/10/2分前、3連複を10/2分前に取得し、出馬表3回を含め1競走14回。2場24Rは336回、3場36Rは504回になる。

開始時に `planned_odds`・`planned_requests`・`request_limit` を表示する。明示上限で未処理を残す場合は `reason=request_limit_reached` と `unprocessed_odds` を表示し終了コード1を返す。未処理件数には、保存済みか未確認の将来時点も含む。上限ちょうどで全件完了した場合は正常終了。個別失敗がある場合も終了コード1。

### `collect-netkeiba-results`

netkeiba の結果ページを analysis SQLite へ取り込む。

主な引数:

- `--from-date`
- `--to-date`
- `--db`
- `--mapping-csv`
- `--use-db-mapping`
- `--max-live-requests`
- `--min-interval-seconds`
- `--refresh`
- `--retries`
- `--dry-run`
- `--limit`

### `generate-netkeiba-mapping`

analysis SQLite のレース情報から netkeiba 対応表を生成する。

主な引数:

- `--from-date`
- `--to-date`
- `--db`
- `--output`
- `--meeting-calendar-csv`
- `--save-to-db`
- `--limit`

### `backfill-analysis-runners`

analysis SQLite の runner 欠損を既存レースから補完する。

主な引数:

- `--db`
- `--from-date`
- `--to-date`
- `--courses`
- `--only-missing`
- `--retries`
- `--min-interval-seconds`
- `--limit`
- `--dry-run`

### `verify-analysis-joins`

analysis SQLite の card / result join 健全性を確認する。

主な引数:

- `--db`
- `--from-date`
- `--to-date`
- `--sample-size`

### `fetch-nankankeiba-pattern`

南関勝ちパターン分析を 1 件取得して整形表示する。

主な引数:

- `--date`
- `--course`
- `--meeting`
- `--day`
- `--race`
- `--periods`
- `--categories`
- `--output`

### `call-local-api`

ローカル HTTP API を叩いて整形 JSON を出力する。

主な引数:

- `path`
- `--base-url`
- `--query key=value`
- `--output`

例:

```powershell
uv run jra-srb call-local-api "/nankan/meetings/2026-07-08/kawasaki/races/8/card"
uv run jra-srb call-local-api "/races/202603220611/odds" --query "bet_type=quinella" --query "combination=10,11"
```

### `fetch-nankan-prediction-bundle`

南関予想用 bundle をローカル API 経由で取得する。

主な引数:

- `--date`
- `--course`
- `--race`
- `--meeting`
- `--day`
- `--bet-types`
- `--base-url`
- `--refresh`
- `--output`

例:

```powershell
uv run jra-srb fetch-nankan-prediction-bundle --date 2026-07-06 --course kawasaki --race 1 --meeting 4 --day 1
```

### `import-daily-prediction-log`

日次予想 Markdown ログを analysis SQLite に取り込む。

主な引数:

- `path`
- `--db`

## 関連環境変数

- `JRA_SRB_ANALYSIS_DB_PATH`
  - analysis SQLite の既定パス
- `JRA_SRB_LOCAL_API_BASE_URL`
  - ローカル API 呼び出し系コマンドの既定 base URL

## 更新ルール

- コマンド追加時はこの文書を更新する
- 実運用フローまで説明する必要がある場合は [04_利用ガイド.md](/D:/develop/jra-scr/docs/jra/04_利用ガイド.md) に追記する
