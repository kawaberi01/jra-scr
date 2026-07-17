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

## 7. フェーズ2追加確認

- `parse_race_card()`はJRA HTMLのrunner候補行数と変換成功数を比較していない。
- `RaceCard.data_status`は存在するが、JRA側では生成されず、現状は南関の馬体重状態だけで使われている。
- JRA HTML fixtureには通常cardしかなく、取消fixtureはない。取消・除外の明示判定は行テキストを使う必要がある。
- `JraService.get_race_card_by_number()`は180秒cacheを使い、強制再取得引数を持たない。
- 定刻オッズcollectorは各観測時点でrace最新値とオッズだけを保存し、cardを保存しない。
- 保存済みsnapshot APIは`as_of`入力を持たず、`races/runners`最新値と全時点中の最新オッズを合成する。
- SQLiteの日時はISO 8601文字列で保存されるため、異なるoffsetを含む境界比較には`julianday()`を使う必要がある。

## 8. 要件との差分確定

| 項目 | 現行 | 変更後 |
| --- | --- | --- |
| card世代 | 最新値のみ | 取得ごとにappend |
| runner集合品質 | 未判定 | `complete/incomplete`を保存 |
| 取消 | 表現なし | `active/withdrawn`と`explicit/derived` |
| 馬体重 | extractorのみ | 履歴・最新値・保存APIへ保持 |
| 結果page | cardへfallback | 最新値互換のみ。発走前履歴から除外 |
| API時点 | 指定不可 | timezone付き`as_of`以下を合成 |
| オッズ時点 | 全期間の最新 | `as_of`指定時は境界以下の最新 |
| 旧DB | 最新値参照 | `as_of`省略時のみfallback |
