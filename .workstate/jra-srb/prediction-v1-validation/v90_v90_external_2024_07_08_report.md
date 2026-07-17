# Prediction Evaluation Report

## 対象
- theory_version: v90
- theory_note: v86 summer-circuit baseline: Sapporo/Hakodate/Fukushima/Niigata/Kokura only
- evaluation_period: 2024-07-01..2024-08-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v90
- theory_note: v86 summer-circuit baseline: Sapporo/Hakodate/Fukushima/Niigata/Kokura only
- evaluation_period: 2024-07-01..2024-08-31
- candidate_races: 563
- evaluated_races: 432
- excluded_races: 131
- bet_races: 25
- tickets: 25
- hits: 2
- total_bet: 2500
- total_payout: 1220
- return_rate: 0.488
- return_rate_without_max_payout: 0.216
- return_rate_without_top3_payouts: 0.0
- axis_top3_rate: 0.5394
- middle_hole_top3_rate: 0.16
- wide_hit_rate: 0.08
- average_tickets_per_evaluated_race: 0.0579
- skip_rate: 0.9421
- exclusion_rate: 0.2327
- max_payout: 680
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 97
- few_candidates:1: 19
- few_candidates:2: 7
- few_candidates:4: 3
- few_candidates:5: 3
- few_candidates:3: 2

## 的中上位
- 2024-08-10 01R6 3歳未勝利: ['1-14'] payout=680 axis=スピードリッチ rank=1
- 2024-07-28 04R6 佐渡ステークス: ['3-11'] payout=540 axis=カナテープ rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
