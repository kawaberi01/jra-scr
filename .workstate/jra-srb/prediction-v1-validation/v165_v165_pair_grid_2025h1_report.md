# Prediction Evaluation Report

## 対象
- theory_version: v165
- theory_note: pair-direct: odds ratio at most 2
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v165
- theory_note: pair-direct: odds ratio at most 2
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 18
- tickets: 18
- hits: 2
- total_bet: 1800
- total_payout: 1430
- return_rate: 0.7944
- return_rate_without_max_payout: 0.2833
- return_rate_without_top3_payouts: 0.0
- axis_top3_rate: 0.0059
- middle_hole_top3_rate: 0.3333
- wide_hit_rate: 0.1111
- average_tickets_per_evaluated_race: 0.0214
- skip_rate: 0.9786
- exclusion_rate: 0.5119
- max_payout: 920
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
- 2025-02-01 05R9 白嶺ステークス: ['8-16'] payout=920 axis=ナイトアクアリウム rank=3
- 2025-05-24 05R11 欅ステークス: ['12-13'] payout=510 axis=コンクイスタ rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
