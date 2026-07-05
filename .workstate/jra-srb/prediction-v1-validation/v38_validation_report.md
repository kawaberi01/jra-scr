# Prediction Evaluation Report

## 対象
- theory_version: v38
- theory_note: target-filter test: v25 plus require middle same-course top3 >= 0.25
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v38
- theory_note: target-filter test: v25 plus require middle same-course top3 >= 0.25
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 108
- tickets: 178
- hits: 27
- total_bet: 17800
- total_payout: 16370
- return_rate: 0.9197
- return_rate_without_max_payout: 0.8657
- return_rate_without_top3_payouts: 0.7635
- axis_top3_rate: 0.5564
- middle_hole_top3_rate: 0.3034
- wide_hit_rate: 0.1517
- average_tickets_per_evaluated_race: 0.3236
- skip_rate: 0.8036
- exclusion_rate: 0.3452
- max_payout: 960
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
- 2025-10-04 08R8 3歳以上2勝クラス: ['2-10'] payout=960 axis=ヴァリディシームス rank=3
- 2025-10-04 05R12 3歳以上2勝クラス: ['1-2'] payout=930 axis=フウセツ rank=2
- 2025-10-12 08R12 3歳以上1勝クラス: ['13-17'] payout=890 axis=シャイフ rank=3
- 2025-12-07 09R9 豊中特別: ['1-4'] payout=890 axis=タマモキャリコ rank=1
- 2025-10-05 08R6 3歳以上1勝クラス: ['7-14'] payout=850 axis=エコロスパーダ rank=2
- 2025-10-05 08R8 3歳以上2勝クラス: ['5-14'] payout=840 axis=ピエマンソン rank=2
- 2025-10-19 04R12 3歳以上1勝クラス: ['2-10'] payout=840 axis=スノーサイレンス rank=1
- 2025-10-19 05R12 甲斐路ステークス: ['5-16'] payout=800 axis=ジョイフルニュース rank=2
- 2025-12-07 07R10 志摩特別: ['1-13'] payout=780 axis=テラメリタ rank=3
- 2025-11-16 05R12 3歳以上1勝クラス: ['11-13'] payout=730 axis=エデルクローネ rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
