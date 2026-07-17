# Prediction Evaluation Report

## 対象
- theory_version: v181
- theory_note: pair-direct: middle odds floor 14
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v181
- theory_note: pair-direct: middle odds floor 14
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 38
- tickets: 38
- hits: 4
- total_bet: 3800
- total_payout: 2830
- return_rate: 0.7447
- return_rate_without_max_payout: 0.4579
- return_rate_without_top3_payouts: 0.0842
- axis_top3_rate: 0.0581
- middle_hole_top3_rate: 0.1842
- wide_hit_rate: 0.1053
- average_tickets_per_evaluated_race: 0.0451
- skip_rate: 0.9549
- exclusion_rate: 0.5119
- max_payout: 1090
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
- 2025-06-15 05R6 3歳以上1勝クラス: ['1-5'] payout=1090 axis=プレシャスデイ rank=2
- 2025-03-08 06R10 上総ステークス: ['2-15'] payout=810 axis=ロードクロンヌ rank=1
- 2025-06-15 02R11 函館日刊スポーツ杯: ['2-5'] payout=610 axis=ドゥアムール rank=1
- 2025-04-26 05R12 4歳以上2勝クラス: ['13-14'] payout=320 axis=ターコイズフリンジ rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
