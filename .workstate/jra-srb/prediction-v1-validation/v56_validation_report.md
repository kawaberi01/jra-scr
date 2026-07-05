# Prediction Evaluation Report

## 対象
- theory_version: v56
- theory_note: targeted-guard test: v53 plus axis popularity <= 2
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v56
- theory_note: targeted-guard test: v53 plus axis popularity <= 2
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 141
- tickets: 255
- hits: 42
- total_bet: 25500
- total_payout: 25890
- return_rate: 1.0153
- return_rate_without_max_payout: 0.9671
- return_rate_without_top3_payouts: 0.8827
- axis_top3_rate: 0.6036
- middle_hole_top3_rate: 0.3137
- wide_hit_rate: 0.1647
- average_tickets_per_evaluated_race: 0.4636
- skip_rate: 0.7436
- exclusion_rate: 0.3452
- max_payout: 1230
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
- 2025-10-13 05R7 3歳以上1勝クラス: ['7-16'] payout=1230 axis=タマモトリノ rank=2
- 2025-12-14 07R7 3歳以上1勝クラス: ['12-13'] payout=1090 axis=トーアケルキラ rank=2
- 2025-11-16 03R8 3歳以上1勝クラス: ['6-13'] payout=1060 axis=ディニトーソ rank=1
- 2025-12-06 07R7 3歳以上1勝クラス: ['14-15'] payout=1060 axis=ホウオウサムレット rank=3
- 2025-12-20 07R3 3歳以上1勝クラス: ['9-14'] payout=980 axis=ディニテ rank=2
- 2025-10-04 08R8 3歳以上2勝クラス: ['2-10'] payout=960 axis=ヴァリディシームス rank=3
- 2025-11-16 05R7 3歳以上2勝クラス: ['4-7'] payout=940 axis=メイショウハチロー rank=1
- 2025-11-09 05R1 2歳未勝利: ['10-13'] payout=910 axis=ニシノマーレ rank=3
- 2025-12-21 07R7 3歳以上1勝クラス: ['12-14'] payout=870 axis=ペレグリン rank=3
- 2025-10-18 04R7 3歳以上1勝クラス: ['2-15', '2-14'] payout=850 axis=ミエノフェアリー rank=2

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
