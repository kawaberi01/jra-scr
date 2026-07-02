# netkeiba analysis.sqlite persistence 実装指示書

## 対象機能
netkeiba `race_result` / 指定済み `odds_view` を `analysis.sqlite` に永続保存する。

## 変更してよい範囲
- `AnalysisSQLiteStore` のスキーマと netkeiba 用メソッド追加。
- netkeiba result 収集用の小さな collector 追加。
- CLI サブコマンド追加。
- 関連テスト追加。

## 変更してはいけない範囲
- 既存 JRA 公式取得のテーブル契約、API 契約、CLI 契約。
- netkeiba odds の全件バルク保存。
- 予想エージェント本体。
- JRA race_id と netkeiba race_id の推測マッピング。

## 実装順序
1. `AnalysisSQLiteStore.init_db()` に `netkeiba_*` テーブルを追加する。
2. `has_netkeiba_result`, `write_netkeiba_result`, `has_netkeiba_odds_entry`, `write_netkeiba_odds` を追加する。
3. `NetkeibaResultCollectionOptions`, `NetkeibaRaceTarget`, `NetkeibaAnalysisCollector` を追加する。
4. CLI `collect-netkeiba-results` を追加する。
5. store/CLI テストを追加する。
6. pytest を実行する。

## テスト観点
- スキーマ作成で netkeiba テーブルが存在する。
- result 保存で race/result_entries/payouts が保存される。
- odds 保存で指定済み entry のみ保存される。
- CLI parser が `collect-netkeiba-results` を受け付ける。
- collector は保存済み result を `--refresh` なしでスキップする。

## 停止条件
- 対応表なしに JRA race_id と netkeiba race_id の自動照合が必要になった場合は実装しない。
- 既存 JRA API/DB への破壊的変更が必要になった場合は止める。
