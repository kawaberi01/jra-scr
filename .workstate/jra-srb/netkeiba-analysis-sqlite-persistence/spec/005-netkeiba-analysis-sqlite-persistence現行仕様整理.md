# netkeiba analysis.sqlite persistence 現行仕様整理

## 現行構成
- `src/jra_srb/analysis_store.py`
  - `AnalysisSQLiteStore` が `analysis.sqlite` のスキーマ作成と JRA 由来データの保存を担う。
  - `races`, `runners`, `odds_snapshots`, `odds_entries`, `race_results`, `result_entries`, `payouts` などを作成する。
  - `write_race`, `write_card`, `write_odds`, `write_result`, `write_error` で書き込みを行う。
- `src/jra_srb/netkeiba_service.py`
  - `get_race_result(race_id)` で netkeiba `race_result` を取得して `NetkeibaRaceResult` を返す。
  - `get_race_odds(race_id, bet_type, combination, refresh)` で `odds_view` と odds API を取得し、`RaceOdds` を返す。
  - combination の順不同/順序あり正規化は service 層で完了済み。
- `src/jra_srb/cli.py`
  - `collect-analysis` など JRA analysis DB 用コマンドがある。
  - netkeiba 永続保存用 CLI は未実装。

## 不足
- netkeiba 補完データ用テーブルがない。
- `NetkeibaRaceResult` / netkeiba odds を `analysis.sqlite` に保存する store メソッドがない。
- 保存済み netkeiba result/odds を確認してライブ取得をスキップする仕組みがない。
- 対応表を入力にした再開可能な netkeiba 収集 CLI がない。

## 既存維持点
- JRA 公式用 `races`, `race_results`, `odds_entries` などは変更しない。
- netkeiba 由来データは `netkeiba_*` テーブルに分離する。
- 既存 FastAPI の `/netkeiba/races/{race_id}/result` と `/netkeiba/races/{race_id}/odds` の取得契約は壊さない。
