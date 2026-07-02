# netkeiba analysis.sqlite persistence 実装計画書

## 手順
1. `analysis_store.py` に netkeiba 用テーブルを追加する。
2. `analysis_store.py` に netkeiba result/odds の保存・存在確認メソッドを追加する。
3. `netkeiba_analysis_collector.py` を追加し、対応表 CSV ベースの result バッチを実装する。
4. `cli.py` に `collect-netkeiba-results` サブコマンドを追加する。
5. `tests/test_analysis_store.py` に netkeiba テーブル作成、result 保存、odds 保存のテストを追加する。
6. `tests/test_cli.py` に parser とバッチの保存済みスキップ/保存動作テストを追加する。
7. 既存テストを実行し、JRA 側が壊れていないことを確認する。

## 変更対象
- `src/jra_srb/analysis_store.py`
- `src/jra_srb/netkeiba_analysis_collector.py`
- `src/jra_srb/cli.py`
- `tests/test_analysis_store.py`
- `tests/test_cli.py`

## 確認観点
- 既存 JRA analysis テーブルのテストが通る。
- netkeiba result は `netkeiba_race_results`, `netkeiba_result_entries`, `netkeiba_payouts` に保存される。
- netkeiba odds は指定買い目だけ `netkeiba_odds_entries` に保存される。
- 保存済み result は `--refresh` なしで再取得されない。
- `--max-live-requests` で取得数が制限される。
- `--min-interval-seconds` は collector のライブ取得間で使われる。

## リスク
- mapping CSV がない場合、JRA race_id と netkeiba race_id の対応を自動生成できない。
- netkeiba HTML/odds API の変化は既存 extractor/service 側の責務。
