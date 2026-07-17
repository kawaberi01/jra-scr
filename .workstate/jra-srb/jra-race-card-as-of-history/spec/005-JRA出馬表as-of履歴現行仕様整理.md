# 005-JRA出馬表as-of履歴現行仕様整理

## 1. 現行schema

- `races`: `race_id`主キーの最新レース情報。
- `runners`: `(race_id, horse_no)`主キーの最新runner情報。
- `runners`は`horse_weight`、`horse_weight_diff`、取消状態を持たない。

## 2. 現行書込

### `write_race()`

- 開催一覧由来のrace情報をupsertする。
- `fetched_at`は開催一覧の観測時刻。

### `write_card()`

- card由来のrace情報をupsertする。
- cardに含まれるrunnerを個別upsertする。
- cardから消えた既存runnerは削除しない。
- `Runner.horse_weight/horse_weight_diff`は保存しない。

## 3. 現行参照

- `get_pre_race_snapshot()`は現在の`races/runners`だけを読む。
- `as_of`入力はない。
- 結果・払戻は応答へ混ぜないため、結果リーク防止は維持されている。

## 4. 要件との差分

| 要件 | 現行 | 必要な契約 |
| --- | --- | --- |
| 指定時点のrace | 最新値のみ | race snapshot履歴 |
| 指定時点のrunner集合 | runner個別upsert | card集合snapshot |
| 騎手変更 | 上書き | 世代別runner payload |
| 馬体重 | modelにはあるがDBで破棄 | 履歴・DTOへ追加 |
| 取消 | 明示fieldなし、欠落も最新tableに残る | 集合差分と品質条件 |
| 結果リーク防止 | 結果tableを読まない | 維持 |

## 5. 実装前に解決すべき論点

1. card取得が完全成功した時だけ「runner集合が確定」とみなす。
2. 完全集合snapshot間の差分で取消候補を導出し、明示的な取消情報とは区別する。
3. `data_status`が不完全な場合はrunner欠落を取消と判定しない。
4. 最新値APIは互換維持し、`as_of`指定時だけ履歴tableを読む案を優先する。
5. race snapshotとcard snapshotの観測時刻が異なる場合の合成規則を決める。

## 6. フェーズ1停止理由

- DB、collector、extractor/model、公開APIに影響が広がる。
- 取消と不完全取得を誤判定すると履歴の意味が壊れる。
- analysis-orchestratorの広範囲変更停止条件に従い、`010/020/030`作成前に契約を追加確認する。
