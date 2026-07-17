# Prediction Evaluation Report

## 対象
- theory_version: v143
- theory_note: general JRA baseline: all courses, one middle allowed, no race-number ceiling
- evaluation_period: 2025-10-01..2025-12-31
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
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 56
- tickets: 56
- hits: 15
- total_bet: 5600
- total_payout: 9020
- return_rate: 1.6107
- return_rate_without_max_payout: 1.4339
- return_rate_without_top3_payouts: 1.1214
- axis_top3_rate: 0.5836
- middle_hole_top3_rate: 0.4107
- wide_hit_rate: 0.2679
- average_tickets_per_evaluated_race: 0.1018
- skip_rate: 0.8982
- exclusion_rate: 0.3452
- max_payout: 990
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
- 2025-11-29 08R8 3歳以上2勝クラス: ['13-15'] payout=990 axis=マサノユニコーン rank=2
- 2025-12-06 06R11 スポーツニッポン賞ステイヤーズステークス: ['4-7'] payout=980 axis=クロミナンス rank=3
- 2025-10-11 05R2 2歳未勝利: ['11-16'] payout=770 axis=ビップムーラン rank=2
- 2025-10-26 08R10 カノープスステークス: ['3-5'] payout=730 axis=ジューンアヲニヨシ rank=2
- 2025-11-15 05R11 武蔵野ステークス: ['1-4'] payout=700 axis=コスタノヴァ rank=2
- 2025-12-06 09R10 妙見山ステークス: ['2-14'] payout=700 axis=ゲッティヴィラ rank=2
- 2025-11-22 08R12 3歳以上2勝クラス: ['7-14'] payout=620 axis=ミッキーゴールド rank=1
- 2025-11-02 08R6 3歳以上1勝クラス: ['5-9'] payout=590 axis=タケルハーロック rank=3
- 2025-11-09 03R2 2歳未勝利: ['10-15'] payout=560 axis=アンジュプロミス rank=1
- 2025-12-07 06R8 3歳以上2勝クラス: ['2-13'] payout=540 axis=アシャカトベ rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
