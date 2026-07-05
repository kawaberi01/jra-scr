# Prediction Evaluation Report

## 対象
- theory_version: v22
- theory_note: ticket-shape test: keep v17 rules, but buy only the top middle on standard races
- evaluation_period: 2025-09-01..2025-09-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v22
- theory_note: ticket-shape test: keep v17 rules, but buy only the top middle on standard races
- evaluation_period: 2025-09-01..2025-09-30
- candidate_races: 240
- evaluated_races: 161
- excluded_races: 79
- bet_races: 134
- tickets: 134
- hits: 19
- total_bet: 13400
- total_payout: 8790
- return_rate: 0.656
- return_rate_without_max_payout: 0.5955
- return_rate_without_top3_payouts: 0.4925
- axis_top3_rate: 0.5901
- middle_hole_top3_rate: 0.2761
- wide_hit_rate: 0.1418
- average_tickets_per_evaluated_race: 0.8323
- skip_rate: 0.1677
- exclusion_rate: 0.3292
- max_payout: 810
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 36
- few_candidates:5: 10
- few_candidates:2: 9
- few_candidates:3: 9
- few_candidates:4: 9
- few_candidates:1: 6

## 的中上位
- 2025-09-14 09R7 3歳以上1勝クラス: ['1-6'] payout=810 axis=ロンドボス rank=1
- 2025-09-20 06R7 3歳以上1勝クラス: ['5-6'] payout=700 axis=ルールーリマ rank=3
- 2025-09-14 06R2 2歳未勝利: ['8-10'] payout=680 axis=フクチャンショウ rank=1
- 2025-09-15 09R6 3歳未勝利: ['2-18'] payout=630 axis=アスクコモンタレヴ rank=1
- 2025-09-13 06R11 初風ステークス: ['6-9'] payout=550 axis=ドンレパルス rank=2
- 2025-09-21 06R11 産経賞オールカマー: ['7-9'] payout=550 axis=ドゥラドーレス rank=2
- 2025-09-07 09R4 3歳未勝利: ['9-10'] payout=530 axis=アスクコモンタレヴ rank=2
- 2025-09-06 09R3 3歳未勝利: ['1-6'] payout=510 axis=ラテライト rank=3
- 2025-09-07 01R8 3歳以上1勝クラス: ['12-15'] payout=500 axis=ブルーアイドガール rank=1
- 2025-09-14 09R10 仲秋ステークス: ['7-8'] payout=500 axis=ラヴァンダ rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
