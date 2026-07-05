# Prediction Evaluation Report

## 対象
- theory_version: v86
- theory_note: v80 plus ticket filters: exclude middle jockey recent 0.15-0.25 and axis odds 4.0-6.0
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v86
- theory_note: v80 plus ticket filters: exclude middle jockey recent 0.15-0.25 and axis odds 4.0-6.0
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 22
- tickets: 22
- hits: 8
- total_bet: 2200
- total_payout: 3930
- return_rate: 1.7864
- return_rate_without_max_payout: 1.4364
- return_rate_without_top3_payouts: 0.9136
- axis_top3_rate: 0.5655
- middle_hole_top3_rate: 0.5455
- wide_hit_rate: 0.3636
- average_tickets_per_evaluated_race: 0.04
- skip_rate: 0.96
- exclusion_rate: 0.3452
- max_payout: 770
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
- 2025-10-11 05R2 2歳未勝利: ['11-16'] payout=770 axis=ビップムーラン rank=2
- 2025-11-02 08R6 3歳以上1勝クラス: ['5-9'] payout=590 axis=タケルハーロック rank=3
- 2025-11-09 03R2 2歳未勝利: ['10-15'] payout=560 axis=アンジュプロミス rank=1
- 2025-11-24 05R5 3歳以上1勝クラス: ['2-3'] payout=530 axis=マックスキュー rank=2
- 2025-10-18 04R7 3歳以上1勝クラス: ['2-15'] payout=410 axis=ミエノフェアリー rank=2
- 2025-10-18 04R6 3歳以上1勝クラス: ['6-8'] payout=380 axis=ゴールデンクラウド rank=1
- 2025-12-20 06R8 3歳以上1勝クラス: ['4-12'] payout=370 axis=ピコテンダー rank=2
- 2025-12-06 06R7 3歳以上1勝クラス: ['5-6'] payout=320 axis=ピコテンダー rank=2

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
