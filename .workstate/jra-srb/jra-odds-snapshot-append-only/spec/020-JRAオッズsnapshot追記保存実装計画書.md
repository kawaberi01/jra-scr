# 020-JRAオッズsnapshot追記保存実装計画書

## 1. 対象と目的

- 対象機能: JRAオッズsnapshot追記保存
- 対象範囲: DB migration、追記保存、参照互換、timeline collector/CLI、test。
- 対象外: runners履歴、保持期間、性能最適化。

## 2. 実装フェーズ

### Phase 1: schema/migration

- 新schemaと旧unique検出・再構築処理を追加する。

### Phase 2: 追記保存

- snapshot IDを世代ごとに生成し、upsert/deleteを廃止する。

### Phase 3: 参照互換

- timelineは全世代、pre-race snapshotは最新世代/券種に固定する。

### Phase 4: collector/CLI

- `refresh_existing`と`--refresh-existing`を追加する。

### Phase 5: test/検証

- store、migration、collector、CLIのtestを追加・修正する。
- 全pytestとruffを実行する。

## 3. タスク一覧

| ID | ステータス | 作業内容 | DoD |
| --- | --- | --- | --- |
| ODDS-01 | pending | 旧schema migration | 既存行を保持しunique解除 |
| ODDS-02 | pending | append-only write | 再保存で2世代保持 |
| ODDS-03 | pending | 参照互換 | timeline全世代、snapshot最新のみ |
| ODDS-04 | pending | collector/CLI option | 明示時のみ再取得 |
| ODDS-05 | pending | test/ruff | 全検証成功 |
| ODDS-06 | pending | 進捗更新 | 共通・個別進捗が最新 |

## 4. 完了判定

- 再取得で過去snapshotとentryが保持される。
- 旧DBが無損失で移行される。
- 既存APIのsnapshot応答形状が維持される。
- pytestとruffが成功する。

## 5. 次タスク候補

- `JRA-NEXT-003` races/runnersのas-of履歴化。
