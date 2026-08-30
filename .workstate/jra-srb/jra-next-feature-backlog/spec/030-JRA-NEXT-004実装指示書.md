# 030-JRA-NEXT-004実装指示書

## 1. 対象概要

- 対象機能: 結果収集 Job registry SQLite 永続化。
- 変更してよい範囲: `jobs.py`、`app.py`、Job API テスト、JRA-NEXT-004 の workstate。
- 変更してはいけない範囲: API path/response model、cancel/retry/concurrency、結果データ storage の仕様。

## 2. 実装順序

1. `jobs.py` に SQLite schema、作成・更新の同期保存、復元を追加する。
2. `app.py` のアプリ registry を `JRA_SRB_JOBS_PATH`（既定 `data/jobs.sqlite`）で初期化する。
3. 永続化・再起動中断のテストを追加する。
4. 対象・全体検証を実行し、進捗を完了へ更新する。

## 3. 実装ルール

- `sqlite3`、`Path`、ISO 8601 文字列の既存パターンに合わせる。
- DB パス省略時の registry は in-memory のままとし、既存単体テストを壊さない。
- `running` の自動再開は実装せず、再起動時に `failed` へ確定する。
- SQL はパラメータ化し、公開モデルへのフィールド追加は行わない。

## 4. レビュー観点

- 作成・全状態遷移が DB へ保存されるか。
- 再起動で queued/succeeded/failed が保持され、running のみ安全に失敗化されるか。
- API の既存 response shape と 404 が維持されるか。
