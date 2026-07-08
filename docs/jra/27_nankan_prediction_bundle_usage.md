# 南関 prediction bundle 利用方法

## 目的

南関予想で毎回まとめて参照する材料を 1 回で取得するための利用手順です。

- 出馬表
- 軽量オッズ
- 当日開催傾向
- 持ち時計
- 上がり時計
- 勝ちパターン分析
- 条件別リーディングジョッキー

個別 API を順番に叩かず、予想入力用の束を 1 レスポンスで受け取りたいときに使います。

## API

```http
GET /nankan/meetings/{date}/{course}/races/{race_no}/prediction-bundle
```

## 必須クエリ

- `meeting_no`
- `meeting_day`

勝ちパターン分析 API が開催回と開催日を必要とするため、bundle でも必須です。

## 任意クエリ

- `bet_types`
- `refresh`

`bet_types` を省略した場合は `win,wide,quinella` を返します。`trio` を含めたい場合だけ明示指定してください。

## API 例

```bash
curl "http://127.0.0.1:8000/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-bundle?meeting_no=4&meeting_day=1"
```

`trio` も含める場合:

```bash
curl "http://127.0.0.1:8000/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-bundle?meeting_no=4&meeting_day=1&bet_types=win,wide,quinella,trio"
```

キャッシュを使わず再取得する場合:

```bash
curl "http://127.0.0.1:8000/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-bundle?meeting_no=4&meeting_day=1&refresh=true"
```

## CLI

```bash
rtk uv run python -m jra_srb.cli fetch-nankan-prediction-bundle --date 2026-07-06 --course kawasaki --race 1 --meeting 4 --day 1
```

JSON ファイルへ保存する場合:

```bash
rtk uv run python -m jra_srb.cli fetch-nankan-prediction-bundle --date 2026-07-06 --course kawasaki --race 1 --meeting 4 --day 1 --output bundle.json
```

`trio` を含める場合:

```bash
rtk uv run python -m jra_srb.cli fetch-nankan-prediction-bundle --date 2026-07-06 --course kawasaki --race 1 --meeting 4 --day 1 --bet-types win,wide,quinella,trio
```

## レスポンスの主な項目

```json
{
  "race_id": "2026070621040101",
  "date": "2026-07-06",
  "course": "kawasaki",
  "race_no": 1,
  "meeting_no": 4,
  "meeting_day": 1,
  "odds_bet_types": ["win", "wide", "quinella"],
  "card": {},
  "odds_summary": {},
  "trend_context": {},
  "best_time": {},
  "closing_speed": {},
  "pattern": {},
  "leading_jockeys": {},
  "cache_hit": false,
  "meta": {
    "parallelized": true,
    "used_existing_services": true
  }
}
```

## 予想側での使い方

- `card`: 距離、馬場、馬体重、発走時刻の基礎情報
- `odds_summary`: 市場評価の確認。全券種ではなく軽量オッズだけ使う
- `trend_context`: 当日バイアスの確認
- `best_time`: ベース能力の比較
- `closing_speed`: 終い性能の比較
- `pattern`: 条件適性の裏付け
- `leading_jockeys`: 騎手補正

まず `card` と `trend_context` で条件を固め、その後に `best_time`、`closing_speed`、`pattern` を見る流れが扱いやすいです。`odds_summary` は最後に妙味確認として使う前提です。

## 補足

- `prediction-bundle` は既存サービスを並列呼び出しして組み立てます。
- `cache_hit=true` は構成要素がすべてキャッシュ由来だった場合だけ立ちます。
- `leading_jockeys` は `card` の距離と馬場状態を使って条件を自動決定します。
- 個別材料を深掘りしたい場合は既存の `card`、`best-time`、`closing-speed`、`pattern`、`leading/jockeys` API を直接使ってください。
