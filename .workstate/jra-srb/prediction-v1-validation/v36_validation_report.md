# Prediction Evaluation Report

## 対象
- theory_version: v36
- theory_note: target-filter test: v25 plus require middle trainer recent top3 >= 0.20
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v36
- theory_note: target-filter test: v25 plus require middle trainer recent top3 >= 0.20
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 217
- tickets: 390
- hits: 53
- total_bet: 39000
- total_payout: 35990
- return_rate: 0.9228
- return_rate_without_max_payout: 0.8623
- return_rate_without_top3_payouts: 0.7926
- axis_top3_rate: 0.5564
- middle_hole_top3_rate: 0.2692
- wide_hit_rate: 0.1359
- average_tickets_per_evaluated_race: 0.7091
- skip_rate: 0.6055
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
- 2025-11-24 03R10 五色沼特別: ['1-6'] payout=1380 axis=コンドゥイア rank=2
- 2025-10-18 08R11 トルマリンステークス: ['6-9'] payout=1340 axis=パルクリチュード rank=2
- 2025-10-13 05R7 3歳以上1勝クラス: ['7-16'] payout=1230 axis=タマモトリノ rank=2
- 2025-12-06 09R10 妙見山ステークス: ['2-14', '14-15'] payout=1230 axis=ゲッティヴィラ rank=2
- 2025-11-30 08R8 3歳以上2勝クラス: ['5-8', '1-5'] payout=1080 axis=クルミナーレ rank=2
- 2025-12-06 07R11 飛騨ステークス: ['6-9'] payout=1060 axis=レディマリオン rank=1
- 2025-10-19 04R11 新潟牝馬ステークス: ['2-5', '5-12'] payout=1050 axis=カネラフィーナ rank=1
- 2025-10-19 04R8 3歳以上1勝クラス: ['3-14'] payout=970 axis=オオタチ rank=3
- 2025-10-04 08R8 3歳以上2勝クラス: ['2-10'] payout=960 axis=ヴァリディシームス rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
