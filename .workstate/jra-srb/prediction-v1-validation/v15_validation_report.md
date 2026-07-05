# Prediction Evaluation Report

## 対象
- theory_version: v15
- theory_note: score-gap follow-up: keep v11 rules, but require first middle axis-score gap > 10.0
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v15
- theory_note: score-gap follow-up: keep v11 rules, but require first middle axis-score gap > 10.0
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 368
- tickets: 736
- hits: 102
- total_bet: 73600
- total_payout: 73430
- return_rate: 0.9977
- return_rate_without_max_payout: 0.9656
- return_rate_without_top3_payouts: 0.9136
- axis_top3_rate: 0.5309
- middle_hole_top3_rate: 0.2731
- wide_hit_rate: 0.1386
- average_tickets_per_evaluated_race: 1.3382
- skip_rate: 0.3309
- exclusion_rate: 0.3452
- max_payout: 2360
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
- 2025-12-07 07R2 3歳以上1勝クラス: ['11-16'] payout=2360 axis=アクアマリーナ rank=3
- 2025-12-06 09R8 3歳以上2勝クラス: ['8-10'] payout=2090 axis=ペイシャケイプ rank=3
- 2025-10-04 05R10 白秋ステークス: ['7-13'] payout=1740 axis=スカイハイ rank=3
- 2025-11-09 08R11 みやこステークス: ['5-12'] payout=1720 axis=ダブルハートボンド rank=1
- 2025-10-19 04R10 飛翼特別: ['7-18'] payout=1710 axis=ベイビーキッス rank=1
- 2025-12-06 09R10 妙見山ステークス: ['2-15'] payout=1590 axis=ファムエレガンテ rank=1
- 2025-11-24 03R10 五色沼特別: ['1-6'] payout=1380 axis=コンドゥイア rank=2
- 2025-11-15 08R10 アンドロメダステークス: ['9-16'] payout=1350 axis=シェイクユアハート rank=2
- 2025-10-18 08R11 トルマリンステークス: ['6-9'] payout=1340 axis=パルクリチュード rank=2
- 2025-12-20 09R11 タンザナイトステークス: ['5-14'] payout=1300 axis=ヤブサメ rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
