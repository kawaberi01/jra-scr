# Prediction Evaluation Report

## 対象
- theory_version: v12
- theory_note: train-robustness test: keep v9 rules, but narrow middle win odds to 8.0..18.0
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v12
- theory_note: train-robustness test: keep v9 rules, but narrow middle win odds to 8.0..18.0
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 367
- tickets: 734
- hits: 86
- total_bet: 73400
- total_payout: 67060
- return_rate: 0.9136
- return_rate_without_max_payout: 0.871
- return_rate_without_top3_payouts: 0.8075
- axis_top3_rate: 0.4964
- middle_hole_top3_rate: 0.2643
- wide_hit_rate: 0.1172
- average_tickets_per_evaluated_race: 1.3345
- skip_rate: 0.3327
- exclusion_rate: 0.3452
- max_payout: 3130
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 127
- few_candidates:3: 55
- few_candidates:4: 39
- few_candidates:5: 32
- few_candidates:2: 23
- few_candidates:1: 14

## 的中上位
- 2025-10-04 08R7 3歳以上1勝クラス: ['6-16'] payout=3130 axis=セディバン rank=3
- 2025-12-20 06R11 ターコイズステークス: ['1-5'] payout=2570 axis=リラボニート rank=2
- 2025-11-23 05R12 3歳以上2勝クラス: ['10-12', '8-10'] payout=2290 axis=ミクストベリーズ rank=3
- 2025-12-06 09R8 3歳以上2勝クラス: ['8-10'] payout=2090 axis=ペイシャケイプ rank=3
- 2025-11-30 05R8 ベゴニア賞: ['3-8'] payout=1850 axis=コルテオソレイユ rank=2
- 2025-12-06 06R8 イルミネーションジャンプステークス: ['1-4'] payout=1780 axis=ホウオウエクレール rank=3
- 2025-10-19 04R6 3歳以上1勝クラス: ['5-11'] payout=1640 axis=ダイシンレアレア rank=3
- 2025-12-06 09R10 妙見山ステークス: ['2-15'] payout=1590 axis=ファムエレガンテ rank=1
- 2025-12-07 06R9 南総ステークス: ['9-11'] payout=1440 axis=シンバーシア rank=1
- 2025-11-24 03R10 五色沼特別: ['1-6'] payout=1380 axis=コンドゥイア rank=2

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
