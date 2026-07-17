# Prediction Evaluation Report

## 対象
- theory_version: v188
- theory_note: pair-direct: field size at least 17
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v188
- theory_note: pair-direct: field size at least 17
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 21
- tickets: 21
- hits: 1
- total_bet: 2100
- total_payout: 550
- return_rate: 0.2619
- return_rate_without_max_payout: 0.0
- return_rate_without_top3_payouts: 0.0
- axis_top3_rate: 0.2444
- middle_hole_top3_rate: 0.1905
- wide_hit_rate: 0.0476
- average_tickets_per_evaluated_race: 0.0249
- skip_rate: 0.9751
- exclusion_rate: 0.5119
- max_payout: 550
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 278
- few_candidates:1: 273
- few_candidates:2: 153
- few_candidates:3: 91
- few_candidates:4: 54
- few_candidates:5: 35

## 的中上位
- 2025-05-18 05R11 ヴィクトリアマイル: ['16-17'] payout=550 axis=アスコリピチェーノ rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
