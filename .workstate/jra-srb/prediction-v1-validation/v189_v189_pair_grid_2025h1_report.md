# Prediction Evaluation Report

## 対象
- theory_version: v189
- theory_note: pair-direct: field size at least 18
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v189
- theory_note: pair-direct: field size at least 18
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 14
- tickets: 14
- hits: 0
- total_bet: 1400
- total_payout: 0
- return_rate: 0.0
- return_rate_without_max_payout: 0.0
- return_rate_without_top3_payouts: 0.0
- axis_top3_rate: 0.2444
- middle_hole_top3_rate: 0.1429
- wide_hit_rate: 0.0
- average_tickets_per_evaluated_race: 0.0166
- skip_rate: 0.9834
- exclusion_rate: 0.5119
- max_payout: 0
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

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
