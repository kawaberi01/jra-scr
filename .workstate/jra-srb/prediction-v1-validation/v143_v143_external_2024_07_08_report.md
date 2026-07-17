# Prediction Evaluation Report

## 対象
- theory_version: v143
- theory_note: general JRA baseline: all courses, one middle allowed, no race-number ceiling
- evaluation_period: 2024-07-01..2024-08-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v143
- theory_note: general JRA baseline: all courses, one middle allowed, no race-number ceiling
- evaluation_period: 2024-07-01..2024-08-31
- candidate_races: 563
- evaluated_races: 432
- excluded_races: 131
- bet_races: 47
- tickets: 47
- hits: 7
- total_bet: 4700
- total_payout: 4260
- return_rate: 0.9064
- return_rate_without_max_payout: 0.7064
- return_rate_without_top3_payouts: 0.3681
- axis_top3_rate: 0.5394
- middle_hole_top3_rate: 0.234
- wide_hit_rate: 0.1489
- average_tickets_per_evaluated_race: 0.1088
- skip_rate: 0.8912
- exclusion_rate: 0.2327
- max_payout: 940
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
- 2024-07-20 03R11 TUF杯: ['1-5'] payout=940 axis=エスカル rank=1
- 2024-08-10 01R12 3歳以上1勝クラス: ['12-13'] payout=910 axis=ジョーメッドヴィン rank=1
- 2024-08-10 01R6 3歳未勝利: ['1-14'] payout=680 axis=スピードリッチ rank=1
- 2024-07-14 03R10 阿武隈ステークス: ['1-14'] payout=610 axis=ココクレーター rank=3
- 2024-07-28 04R6 佐渡ステークス: ['3-11'] payout=540 axis=カナテープ rank=3
- 2024-08-03 01R9 旭川特別: ['6-14'] payout=300 axis=アンドアイラヴハー rank=2
- 2024-08-31 04R9 瓢湖特別 韓国賞: ['4-5'] payout=280 axis=ベンサレム rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
