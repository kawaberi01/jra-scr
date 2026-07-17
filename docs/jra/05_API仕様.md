# API仕様

この文書は `src/jra_srb/app.py` に実装されている HTTP API の正本です。補助資料側の個別説明より、ここを優先してください。

## 共通

- Base URL: `http://127.0.0.1:8000`
- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`
- MCP HTTP endpoint: `/mcp`

主なクエリ慣習:

- `refresh=true`
  - キャッシュを避けて再取得する
- `bet_type`
  - 単一券種を指定する
- `bet_types`
  - 複数券種をカンマ区切りで指定する

## ヘルス・共通補助

### `GET /health`

API プロセスの生存確認。

### `GET /health/upstream`

JRA upstream への軽量な到達性確認。

### `GET /normalize`

日本語の開催場名、レース表記、券種名を API 用コードへ正規化する。

主なクエリ:

- `course`
- `race`
- `bet_type`
- `combination`

### `GET /races`

日付と開催場から JRA race summary 一覧を返す。

主なクエリ:

- `date`
- `course`

### `GET /search/races`

日付、開催場、キーワードから `race_id` を検索する。

主なクエリ:

- `date`
- `course`
- `keyword`

## JRA 公式 API

### `GET /meetings/{date_}/{course}`

開催日・開催場ベースの JRA レース一覧。

### `GET /races/{race_id}/card`
### `GET /meetings/{date_}/{course}/races/{race_no}/card`

JRA 出馬表。

### `GET /races/{race_id}/odds`
### `GET /meetings/{date_}/{course}/races/{race_no}/odds`

JRA オッズ。

主なクエリ:

- `bet_type`
- `bet_types`
- `combination`
- `refresh`

### `GET /races/{race_id}/result`
### `GET /meetings/{date_}/{course}/races/{race_no}/result`

JRA 結果・払戻。

## netkeiba 補完 API

### `GET /netkeiba/races/{race_id}/result`

netkeiba の過去レース結果ページから補完結果を返す。

### `GET /netkeiba/races/{race_id}/odds`

netkeiba のオッズページから補完オッズを返す。

主なクエリ:

- `bet_type`
- `combination`
- `refresh`

## NAR API

### `GET /nar/calendar`

地方競馬開催カレンダー。

### `GET /nar/meetings/{date_}/{course}`

地方競馬の開催日・開催場ベース一覧。

### `GET /nar/races/{race_id}/card`
### `GET /nar/races/{race_id}/result`
### `GET /nar/races/{race_id}/odds`

地方競馬 race_id ベースの出馬表・結果・オッズ。

## 南関東公式 API

対象開催場:

- `urawa`
- `funabashi`
- `ohi`
- `kawasaki`

### `GET /nankan/leading/jockeys`

条件別リーディングジョッキー情報。

主なクエリ:

- `course`
- `distance`
- `track_condition`
- `period`
- `sort`
- `refresh`

### `GET /nankan/meetings/{date_}/{course}`

南関の開催一覧。

主なクエリ:

- `refresh`

### `GET /nankan/meetings/{date_}/{course}/trend`

開催単位の当日傾向。最新スナップショットを返す。

主なクエリ:

- `refresh`

### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/trend-context`

対象レース時点で当日傾向を採用可能か判定した結果を返す。

主なレスポンス項目:

- `race_count_completed`
- `required_max_completed`
- `usable`
- `reason`

### `GET /nankan/races/{race_id}/card`
### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/card`

南関出馬表。

補足:

- `data_status.horse_weight`
  - `available`
  - `unpublished`
  - `unavailable`

### `GET /nankan/races/{race_id}/best-time`
### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/best-time`

南関持ち時計。

### `GET /nankan/races/{race_id}/closing-speed`
### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/closing-speed`

南関上がり時計。

### `GET /nankan/races/{race_id}/style-profile`
### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/style-profile`

近走通過順ベースの脚質推定。

### `GET /nankan/races/{race_id}/odds`
### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds`

南関オッズ。

主なクエリ:

- `bet_type`
- `bet_types`
- `combination`
- `refresh`

### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds-summary`

予想向けの軽量オッズ。

主なクエリ:

- `bet_types`
- `refresh`

### `GET /nankan/races/{race_id}/result`
### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/result`

南関結果・払戻。

### `GET /nankan/meetings/{date_}/{course}/races/{race_no}/prediction-bundle`

南関予想用の束データ。

必須クエリ:

- `meeting_no`
- `meeting_day`

任意クエリ:

- `bet_types`
- `refresh`

主なレスポンス項目:

- `card`
- `odds_summary`
- `trend_context`
- `best_time`
- `closing_speed`
- `pattern`
- `leading_jockeys`

## 南関勝ちパターン分析 API

### `GET /nankankeiba/pattern/meetings/{date_}/{course}/races/{race_no}`

南関サイト由来の勝ちパターン分析。

主なクエリ:

- `meeting_no`
- `meeting_day`

補足資料:

- [15_nankankeiba_pattern_usage.md](/D:/develop/jra-scr/docs/jra/15_nankankeiba_pattern_usage.md)

## JRA予想・評価参照 API

### `GET /jra/predictions`

保存済みJRA予想を一覧取得する。主なクエリは `race_id`、`from_date`、`to_date`、`theory_version`、`mode`、`limit`、`offset`。レスポンスは `items`、`total`、`limit`、`offset` を持つ。

### `GET /jra/predictions/{prediction_id}`

保存済みJRA予想の詳細と `prediction_tickets` を取得する。保存時のJSONは `pre_race_snapshot` と `prediction` として返す。

### `GET /jra/evaluations`

保存済みJRA予想評価を一覧取得する。主なクエリは `prediction_id`、`race_id`、`from_date`、`to_date`、`theory_version`、`limit`、`offset`。

### `GET /jra/evaluations/{evaluation_id}`

保存済みJRA予想評価の詳細と `ticket_results` を取得する。保存時のJSONは `evaluation` として返す。

### `GET /jra/evaluations/summary`

`from_date`、`to_date`、`theory_version` で絞り込み、購入額、払戻、回収率、的中率、ガミ率、軸・中穴・花火指標、最大払戻除外後回収率を集計する。

共通仕様:

- `race_id` は12桁のJRA形式。
- `limit` は既定100、最大500。`offset` は既定0。
- `from_date` が `to_date` より後の場合は400。
- 詳細が存在しない場合は404。

## 保存済み結果 API

### `GET /stored/results`

保存済み結果を検索する。

主なクエリ:

- `from_date`
- `to_date`
- `course`
- `limit`
- `offset`

### `GET /stored/results/{race_id}`

保存済み結果を `race_id` で取得する。

## 実買い記録 API

### `POST /bet-records`

実買い記録を作成する。

### `GET /bet-records`

実買い記録一覧を取得する。

### `GET /bet-records/{bet_record_id}`

実買い記録詳細を取得する。

### `POST /bet-records/{bet_record_id}/settle`

実買い記録を精算する。

補足資料:

- [14_実買い記録API仕様案.md](/D:/develop/jra-scr/docs/jra/14_実買い記録API仕様案.md)

## Job API

### `POST /jobs/result-collections`

結果収集 job を作成する。

### `GET /jobs/result-collections`

結果収集 job 一覧を返す。

### `GET /jobs/result-collections/{job_id}`

結果収集 job の詳細を返す。

job status:

- `queued`
- `running`
- `succeeded`
- `failed`

## MCP API

### `GET /mcp`
### `POST /mcp`
### `DELETE /mcp`

FastAPI API を MCP HTTP として公開する入口。

## 更新ルール

- endpoint を追加したら、この文書へ追記する
- 具体的な運用例が必要なら [04_利用ガイド.md](/D:/develop/jra-scr/docs/jra/04_利用ガイド.md) に追記する
- 詳細な特化メモは補助資料へ分離し、ここには API 契約だけを残す
