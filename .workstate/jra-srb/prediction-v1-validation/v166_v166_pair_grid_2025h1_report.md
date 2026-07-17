# Prediction Evaluation Report

## 対象
- theory_version: v166
- theory_note: pair-direct: odds ratio at most 3
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v166
- theory_note: pair-direct: odds ratio at most 3
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 91
- tickets: 91
- hits: 9
- total_bet: 9100
- total_payout: 5610
- return_rate: 0.6165
- return_rate_without_max_payout: 0.522
- return_rate_without_top3_payouts: 0.3571
- axis_top3_rate: 0.0771
- middle_hole_top3_rate: 0.2747
- wide_hit_rate: 0.0989
- average_tickets_per_evaluated_race: 0.1079
- skip_rate: 0.8921
- exclusion_rate: 0.5119
- max_payout: 860
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
- 2025-06-15 05R10 江の島ステークス: ['1-2'] payout=860 axis=カフェグランデ rank=1
- 2025-02-08 05R12 4歳以上1勝クラス: ['14-15'] payout=780 axis=マケズギライ rank=1
- 2025-03-15 09R10 難波ステークス: ['1-11'] payout=720 axis=サブマリーナ rank=1
- 2025-02-01 05R9 白嶺ステークス: ['6-8'] payout=600 axis=サクラトップリアル rank=2
- 2025-04-13 03R6 4歳以上1勝クラス: ['2-10'] payout=560 axis=エルフレスアリー rank=3
- 2025-04-12 03R8 4歳以上1勝クラス: ['7-16'] payout=550 axis=カエルム rank=1
- 2025-01-12 07R8 4歳以上1勝クラス: ['12-13'] payout=520 axis=マイネルフォーコン rank=1
- 2025-05-11 04R12 4歳以上1勝クラス: ['9-10'] payout=510 axis=ソングオブライフ rank=1
- 2025-05-24 05R11 欅ステークス: ['12-13'] payout=510 axis=コンクイスタ rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
