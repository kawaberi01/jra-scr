# jra-srb ドキュメント案内

`jra-srb` の API / CLI 説明は、このディレクトリ内の次の 3 文書を正本とします。

## 正本

- [04_利用ガイド.md](/D:/develop/jra-scr/docs/jra/04_利用ガイド.md)
  - セットアップ、起動、典型的な使い方、どの API / CLI を使うかの入口
- [05_API仕様.md](/D:/develop/jra-scr/docs/jra/05_API仕様.md)
  - 現在の HTTP API 一覧と主要パラメータ
- [06_CLI仕様.md](/D:/develop/jra-scr/docs/jra/06_CLI仕様.md)
  - 現在の CLI コマンド一覧と主要オプション

## 土台資料

- [01_プロジェクト概要.md](/D:/develop/jra-scr/docs/jra/01_プロジェクト概要.md)
- [02_アーキテクチャ.md](/D:/develop/jra-scr/docs/jra/02_アーキテクチャ.md)
- [03_設計判断.md](/D:/develop/jra-scr/docs/jra/03_設計判断.md)

## 補助資料

以下は正本ではなく、特定機能の背景、運用メモ、実装時の補助資料です。

- netkeiba 補助
  - [10_netkeiba利用ガイド.md](/D:/develop/jra-scr/docs/jra/10_netkeiba利用ガイド.md)
  - [11_netkeiba_odds_combination_usage.md](/D:/develop/jra-scr/docs/jra/11_netkeiba_odds_combination_usage.md)
  - [13_netkeiba_analysis_sqlite_usage.md](/D:/develop/jra-scr/docs/jra/13_netkeiba_analysis_sqlite_usage.md)
- 南関予想補助
  - [15_nankankeiba_pattern_usage.md](/D:/develop/jra-scr/docs/jra/15_nankankeiba_pattern_usage.md)
  - [16_nankan_card_conditions_usage.md](/D:/develop/jra-scr/docs/jra/16_nankan_card_conditions_usage.md)
  - [17_nankan_prediction_materials_usage.md](/D:/develop/jra-scr/docs/jra/17_nankan_prediction_materials_usage.md)
  - [20_nankan_leading_jockey_usage.md](/D:/develop/jra-scr/docs/jra/20_nankan_leading_jockey_usage.md)
  - [27_nankan_prediction_bundle_usage.md](/D:/develop/jra-scr/docs/jra/27_nankan_prediction_bundle_usage.md)
- API 拡張案・実装メモ
  - [14_実買い記録API仕様案.md](/D:/develop/jra-scr/docs/jra/14_実買い記録API仕様案.md)
  - [18_nankankeiba_pattern_sort_error_fix_prompt.md](/D:/develop/jra-scr/docs/jra/18_nankankeiba_pattern_sort_error_fix_prompt.md)
  - [19_nankan_leading_jockey_instruction.md](/D:/develop/jra-scr/docs/jra/19_nankan_leading_jockey_instruction.md)
  - [21_nankan_leading_jockey_track_condition_fix_prompt.md](/D:/develop/jra-scr/docs/jra/21_nankan_leading_jockey_track_condition_fix_prompt.md)
  - [22_nankan_db_first_ttl_cache_prompt.md](/D:/develop/jra-scr/docs/jra/22_nankan_db_first_ttl_cache_prompt.md)
  - [23_nankan_unpublished_card_data_prompt.md](/D:/develop/jra-scr/docs/jra/23_nankan_unpublished_card_data_prompt.md)
  - [24_nankan_card_data_status_impl_prompt.md](/D:/develop/jra-scr/docs/jra/24_nankan_card_data_status_impl_prompt.md)
  - [25_nankan_trend_asof_race_fix_plan.md](/D:/develop/jra-scr/docs/jra/25_nankan_trend_asof_race_fix_plan.md)
  - [26_nankan_trend_context_runtime_verification_prompt.md](/D:/develop/jra-scr/docs/jra/26_nankan_trend_context_runtime_verification_prompt.md)

## 運用ルール

- API を追加したら、まず [05_API仕様.md](/D:/develop/jra-scr/docs/jra/05_API仕様.md) を更新する
- CLI を追加したら、まず [06_CLI仕様.md](/D:/develop/jra-scr/docs/jra/06_CLI仕様.md) を更新する
- 具体的な使い方が必要なら [04_利用ガイド.md](/D:/develop/jra-scr/docs/jra/04_利用ガイド.md) に追記する
- 個別の実験メモや修正依頼文は正本へ混ぜず、補助資料として分離する
