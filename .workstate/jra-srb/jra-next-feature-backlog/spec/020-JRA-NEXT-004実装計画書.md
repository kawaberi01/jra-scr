# 020-JRA-NEXT-004実装計画書

## 1. 対象と目的

- 対象: `ResultCollectionJobRegistry` と Job API の起動時設定。
- 目的: Job 状態を SQLite へ永続化し、再起動後に参照可能にする。
- 対象外: Job の cancel、retry、同時実行制御。

## 2. タスク一覧

| ID | 作業内容 | 出力 | DoD |
| --- | --- | --- | --- |
| 1 | registry の SQLite schema と保存/復元を追加 | 永続 registry | 全フィールドが保存・復元される |
| 2 | 起動時設定を追加 | `JRA_SRB_JOBS_PATH` | アプリ既定で SQLite を使用する |
| 3 | 再起動時の running Job を失敗化 | 一貫した最終状態 | 自動再実行されない |
| 4 | API 回帰テストを追加 | pytest | 再起動後の一覧・詳細を検証 |
| 5 | lint・全体テスト・進捗更新 | 検証記録 | DoD と結果が記録される |

## 3. 完了判定

- API 再起動後も Job の一覧・詳細・最終状態を参照できる。
- 既存 API path/JSON 契約を変更しない。
- 対象 pytest、全 pytest、ruff、diff check が成功する。
