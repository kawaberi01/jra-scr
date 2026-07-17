# Prediction Evaluation Report

## 対象
- theory_version: v163
- theory_note: pair-direct: axis score gap at least 16
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v163
- theory_note: pair-direct: axis score gap at least 16
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 122
- tickets: 122
- hits: 18
- total_bet: 12200
- total_payout: 11590
- return_rate: 0.95
- return_rate_without_max_payout: 0.8607
- return_rate_without_top3_payouts: 0.7123
- axis_top3_rate: 0.1423
- middle_hole_top3_rate: 0.3115
- wide_hit_rate: 0.1475
- average_tickets_per_evaluated_race: 0.1447
- skip_rate: 0.8553
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
- 2025-05-25 05R8 三峰山特別: ['1-3'] payout=950 axis=エーリアル rank=3
- 2025-06-15 05R10 江の島ステークス: ['1-2'] payout=860 axis=カフェグランデ rank=1
- 2025-03-08 06R10 上総ステークス: ['2-15'] payout=810 axis=ロードクロンヌ rank=1
- 2025-04-12 03R8 4歳以上1勝クラス: ['7-14'] payout=770 axis=カエルム rank=1
- 2025-03-02 06R12 4歳以上2勝クラス: ['5-10'] payout=760 axis=ノットファウンド rank=2
- 2025-01-26 07R10 トリトンステークス: ['5-11'] payout=740 axis=ユハンヌス rank=3
- 2025-03-15 09R10 難波ステークス: ['1-11'] payout=720 axis=サブマリーナ rank=1
- 2025-05-04 08R11 天皇賞(春): ['6-8'] payout=630 axis=ヘデントール rank=1
- 2025-06-15 02R11 函館日刊スポーツ杯: ['2-5'] payout=610 axis=ドゥアムール rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
