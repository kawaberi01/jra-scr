# Prediction Evaluation Report

## 対象
- theory_version: v42
- theory_note: shape-filter test: v25 plus dirt races only and axis odds <= 2.5
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v42
- theory_note: shape-filter test: v25 plus dirt races only and axis odds <= 2.5
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 72
- tickets: 120
- hits: 25
- total_bet: 12000
- total_payout: 12290
- return_rate: 1.0242
- return_rate_without_max_payout: 0.9542
- return_rate_without_top3_payouts: 0.82
- axis_top3_rate: 0.5291
- middle_hole_top3_rate: 0.325
- wide_hit_rate: 0.2083
- average_tickets_per_evaluated_race: 0.2182
- skip_rate: 0.8691
- exclusion_rate: 0.3452
- max_payout: 840
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
- 2025-10-05 08R8 3歳以上2勝クラス: ['5-14'] payout=840 axis=ピエマンソン rank=2
- 2025-10-19 04R12 3歳以上1勝クラス: ['2-10'] payout=840 axis=スノーサイレンス rank=1
- 2025-10-11 05R2 2歳未勝利: ['11-16'] payout=770 axis=ビップムーラン rank=2
- 2025-11-01 05R6 3歳以上1勝クラス: ['4-14'] payout=670 axis=セギレエルビエント rank=1
- 2025-11-29 05R8 3歳以上2勝クラス: ['4-7'] payout=660 axis=ジェイエルマスター rank=3
- 2025-12-06 07R7 3歳以上1勝クラス: ['1-15'] payout=660 axis=ストーンズ rank=1
- 2025-12-07 06R10 市川ステークス: ['3-5'] payout=660 axis=クラウンシエンタ rank=1
- 2025-12-06 06R7 3歳以上1勝クラス: ['5-6', '5-9'] payout=650 axis=ピコテンダー rank=2
- 2025-12-21 06R10 北総ステークス: ['3-15'] payout=600 axis=イムホテプ rank=1
- 2025-12-21 09R9 御影ステークス: ['6-14'] payout=580 axis=ピエマンソン rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
