# API仕様

## `GET /health`

- 用途: ヘルスチェック

## `GET /races?date=YYYY-MM-DD&course=optional`

- 用途: 既存の fixture ベース race summary 一覧

## `GET /meetings/{date}/{course}`

- 用途: 開催地単位の 1R-12R 一覧
- 返却:
  - `race_no`
  - `race_id`
  - `race_name`
  - `start_time`
  - `card_cname`
  - `odds_cname`
  - `result_cname`

## `GET /meetings/{date}/{course}/races/{race_no}/card`

- 用途: 開催日 + 開催地 + レース番号から出馬表取得

## `GET /meetings/{date}/{course}/races/{race_no}/odds`

- 必須クエリ:
  - `bet_type`
- 任意クエリ:
  - `combination=1,2,3`
  - `refresh=true`

### 現在対応している bet_type

- `win`
- `trifecta`

## `GET /meetings/{date}/{course}/races/{race_no}/result`

- 用途: 結果と払戻の同時取得

## 既存の `race_id` ベース API

- `GET /races/{race_id}/card`
- `GET /races/{race_id}/odds`
- `GET /races/{race_id}/result`

## 未対応

- `win`、`trifecta` 以外の JRA 実オッズ券種
- 過去結果バッチの外部 API 化
