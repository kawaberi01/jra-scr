# 005-JRA-NEXT-004現行仕様整理

## 現行の Job API

- `ResultCollectionJobRegistry` は `dict[str, ResultCollectionJobSummary]` のみを保持する。
- 作成時は `queued`、BackgroundTasks 実行中は `running`、終了時は `succeeded` または `failed` へ更新する。
- API の一覧は `created_at` 昇順、詳細は `job_id` 指定で返す。
- `app.py` はモジュール起動時に registry を一つ生成するため、プロセス再起動で全 Job が消える。

## 利用可能な既存パターン

- `batch.py` は `sqlite3` と `Path` を使い、コンストラクタで親ディレクトリ作成と schema 初期化を行う。
- 結果 storage は SQL パラメータを利用し、日時は ISO 8601 文字列で保存している。
- API の既定保存先は環境変数を helper で読み、未指定時は `data/` 配下を使う。
