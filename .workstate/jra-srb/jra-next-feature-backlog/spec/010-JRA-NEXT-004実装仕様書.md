# 010-JRA-NEXT-004実装仕様書

## 0. 最初に読む要約

- 対象機能: 結果収集 Job registry の SQLite 永続化。
- 改修目的: プロセス再起動後も既存 Job API から作成済み Job を参照できるようにする。
- 最重要注意点: API 契約を変えず、再起動時に実行中 Job を自動再実行しない。

## 1. 変更後仕様

- Job の全フィールドを SQLite `result_collection_jobs` テーブルへ作成時・状態更新時に保存する。
- アプリは `JRA_SRB_JOBS_PATH` を registry DB パスとして読み、既定値は `data/jobs.sqlite` とする。
- DB を指定しない直接生成は既存テスト互換の in-memory 動作を維持する。
- 同じ DB を指定して再生成した registry は、全 Job を一覧・詳細で返す。
- 起動時に `running` の Job が残っていた場合は、`failed`、終了時刻、再起動による中断を示す message/error を保存する。`queued`、`succeeded`、`failed` は保存値のまま復元する。

## 2. 実装配置

- 修正: `src/jra_srb/jobs.py` — SQLite schema、読み書き、再起動復元。
- 修正: `src/jra_srb/app.py` — registry DB パスの環境変数と起動時生成。
- 修正: `tests/test_api.py` — SQLite 永続・再起動復元の API 回帰。
- 新規抽象化: なし。既存 registry に局所実装する。

## 3. エラー / ログ / 設定

- Job 未発見の `LookupError` と API の 404 変換は維持する。
- 既存 Job lifecycle ログを維持し、再起動中断も error として復元する。
- DB 接続文字列等の機密値は使用しない。

## 4. テスト観点

- 作成済み Job が別インスタンスで一覧・詳細に復元される。
- 完了 Job の最終状態が再起動後も残る。
- `running` Job が再起動後に `failed` へ確定する。
- 既存 JSONL/SQLite 結果収集 API テストが回帰しない。

## 5. 対象外

- cancel / retry、同時実行数制限、実行途中からの自動再開。
