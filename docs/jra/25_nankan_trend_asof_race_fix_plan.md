# 南関開催傾向 API の時点再現改修案

## 背景

現状の `GET /nankan/meetings/{date}/{course}/trend` は、取得時点で南関公式の
`race_trend/{meeting_id}.do?open_date={YYYYMMDD}` をそのまま解釈して返しています。

このため、例えば `2026-07-07` 川崎 `6R` の事前予想で trend を参照しても、
レスポンスが `race_count_completed = 12` となる場合があります。

これは API が壊れているというより、trend API が
「何R終了時点の傾向か」を指定できない設計になっていることが原因です。

## 現在の問題

事前予想で必要なのは、対象レース直前の時点情報です。

- `1R` 予想なら `0R終了時点`
- `6R` 予想なら `5R終了時点`
- `12R` 予想なら `11R終了時点`

しかし現在の `/trend` は開催全体の最新集計を返すため、
予想対象時点より未来の情報を含む可能性があります。

その結果、予想ロジック側では次のような防御が必要になります。

- `trend.race_count_completed >= 対象race_no` なら事前予想では不採用
- または `trend.race_count_completed > 対象race_no - 1` なら不採用

これは運用としては正しいですが、API としては使い勝手が悪いです。

## 改修方針

trend API を「現時点の傾向」と「対象レース時点に整形した傾向」に分けて扱えるようにします。

### 案1: 既存 endpoint に時点指定を追加

`GET /nankan/meetings/{date}/{course}/trend?as_of_race_no=5`

期待仕様:

- `as_of_race_no` は「5R終了時点まで集計して返す」の意味とする
- `1 <= as_of_race_no <= 12`
- `0` を許可するなら「レース前なので空集計」を返す
- 実データが `race_count_completed = 12` でも、
  `as_of_race_no = 5` 指定時は 5R までに限定して返す

利点:

- endpoint が増えない
- 既存クライアントはそのまま利用可能

注意点:

- 現在の HTML が開催全体集計しか持たないなら、
  スクレイピングだけでは過去時点を復元できない可能性がある

### 案2: 予想用途専用 endpoint を追加

`GET /nankan/meetings/{date}/{course}/races/{race_no}/trend-context`

期待仕様:

- 対象レースの事前予想で使ってよい trend だけ返す
- 未来情報しか取得できない場合は `usable = false`
- 理由を `reason` に入れる

レスポンス例:

```json
{
  "date": "2026-07-07",
  "course": "kawasaki",
  "race_no": 6,
  "usable": false,
  "reason": "latest trend is post-race snapshot",
  "race_count_completed": 12,
  "required_max_completed": 5,
  "summary": {}
}
```

利点:

- 予想ロジック側の判定を API に閉じ込められる
- クライアントが未来情報判定を重複実装しなくてよい

注意点:

- trend 本体 endpoint とは別の責務になる

## 推奨案

まずは `案2` を推奨します。

理由:

- 現在の trend HTML が「開催全体の最新スナップショット」しか持っていない可能性が高い
- その場合、真の意味で `5R終了時点の傾向` を再構築することはできない
- できないものを擬似的に返すより、
  `usable = false` を返して明示的に弾く方が安全

そのうえで、将来的に時点再現可能な材料が増えたら、
`trend-context` 内部で本当に `as_of_race_no` 切り出しを実装するのがよいです。

## 最小改修案

### 1. API 追加

追加候補:

- `GET /nankan/meetings/{date}/{course}/races/{race_no}/trend-context`

レスポンス項目:

- `race_no`
- `race_count_completed`
- `required_max_completed`
- `usable`
- `reason`
- `summary`
- `fetched_at`
- `source`

### 2. サービス追加

`src/jra_srb/nankan_service.py`

追加候補メソッド:

- `get_meeting_trend_context(target_date, course, race_no, refresh=False)`

ロジック:

1. 既存の `get_meeting_trend()` を呼ぶ
2. `required_max_completed = race_no - 1` を計算
3. `trend.race_count_completed <= required_max_completed` なら `usable = true`
4. それ以外は `usable = false`

### 3. endpoint 追加

`src/jra_srb/app.py`

追加候補:

- `/nankan/meetings/{date_}/{course}/races/{race_no}/trend-context`

### 4. 予想側の利用方針

予想ロジックでは今後:

- `/trend` を直接使わず
- `trend-context` を使う

とします。

これで「未来情報なので不採用」という判定を API 側で一元化できます。

## 将来拡張案

もし将来的に公式サイトか別ソースから
「各レース終了ごとの傾向スナップショット」を取れるなら、次を検討します。

1. trend 履歴テーブルを持つ
2. `meeting_id + completed_race_count` 単位で保存する
3. `as_of_race_no` 指定時は最も近い過去スナップショットを返す

この段階に入るまでは、
「時点再現できない場合は不採用」と明示する実装が妥当です。

## 受け入れ条件

- `6R` 事前予想で、最新 trend が `race_count_completed = 12` のとき `usable = false` を返せる
- `1R` 事前予想で、`race_count_completed > 0` の trend は不採用にできる
- `12R` 事前予想で、`race_count_completed <= 11` の場合だけ `usable = true` にできる
- クライアントが「開催後データのため不採用」を理由付きで表示できる

## 実装優先順位

1. `trend-context` の response model 追加
2. `nankan_service.py` に判定メソッド追加
3. `app.py` に endpoint 追加
4. `tests/test_nankan_service.py` と `tests/test_nankan_api.py` に追加テスト
5. 既存の予想スキル利用側で `/trend` 直参照をやめる

