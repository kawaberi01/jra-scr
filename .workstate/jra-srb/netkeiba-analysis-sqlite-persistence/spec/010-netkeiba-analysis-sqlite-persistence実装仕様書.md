# netkeiba analysis.sqlite persistence 実装仕様書

## DB スキーマ
`AnalysisSQLiteStore.init_db()` に以下を追加する。

- `netkeiba_race_results`
  - `netkeiba_race_id text primary key`
  - `jra_race_id text`
  - `race_date text`
  - `course text`
  - `race_no integer`
  - `race_name text`
  - `surface text`
  - `distance text`
  - `direction text`
  - `weather text`
  - `track_condition text`
  - `source text`
  - `fetched_at text`
  - `raw_json text`
- `netkeiba_result_entries`
  - `netkeiba_race_id`, `jra_race_id`, 着順、馬番、馬名、斤量、騎手、調教師、馬体重、上がり、単勝オッズ、人気など。
  - primary key は `(netkeiba_race_id, rank, horse_no)`。
- `netkeiba_payouts`
  - `netkeiba_race_id`, `jra_race_id`, `bet_type`, `combination`, `payout`, `popularity`。
- `netkeiba_odds_entries`
  - `netkeiba_race_id`, `jra_race_id`, `bet_type`, `combination`, `combination_json`, `odds`, `odds_min`, `odds_max`, `popularity`, `fetched_at`, `source`。
  - primary key は `(netkeiba_race_id, bet_type, combination)`。

## Store API
`AnalysisSQLiteStore` に以下を追加する。

- `has_netkeiba_result(netkeiba_race_id: str) -> bool`
  - 保存済み race_result の有無を返す。
- `write_netkeiba_result(result: NetkeibaRaceResult, jra_race_id: str | None = None, raw_json: str | None = None) -> None`
  - result 本体、出走結果、払戻を upsert/delete-insert で保存する。
- `has_netkeiba_odds_entry(netkeiba_race_id: str, bet_type: str, combination: list[str]) -> bool`
  - 指定買い目の保存済み有無を返す。
- `write_netkeiba_odds(odds: RaceOdds, jra_race_id: str | None = None, bet_type: str | None = None) -> None`
  - `RaceOdds.entries` または `RaceOdds.odds` の対象エントリだけを保存する。

## CLI / バッチ
`jra-srb collect-netkeiba-results` を追加する。

入力:
- `--from-date`, `--to-date`
- `--db`
- `--mapping-csv`
- `--max-live-requests`
- `--min-interval-seconds`
- `--refresh`
- `--retries`

CSV:
- 必須列: `netkeiba_race_id`
- 推奨列: `jra_race_id`, `race_date`, `course`, `race_no`
- `race_date` がある場合は `--from-date` / `--to-date` で絞り込む。

動作:
- mapping CSV を読み、対象レースごとに保存済みなら `--refresh` なしではスキップする。
- ライブ取得回数が `--max-live-requests` に達したら停止し、次回再開可能にする。
- ライブ取得間は `--min-interval-seconds` 以上空ける。
- 取得成功時に `write_netkeiba_result` で保存する。
- 失敗時は `collection_errors` に stage `netkeiba-result` で記録する。

## odds 保存方針
- 今回のバッチは result 保存を主対象とする。
- odds は store API を用意し、呼び出し側が `get_race_odds(... bet_type, combination ...)` で絞った `RaceOdds` を保存する。
- wide/trifecta など全件保存は行わない。

## 未対応
- JRA race_id と netkeiba race_id の自動マッピング。
- API endpoint で DB 保存済みレスポンスを直接返す read-through cache。
