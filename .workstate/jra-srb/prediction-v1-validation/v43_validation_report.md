# Prediction Evaluation Report

## 対象
- theory_version: v43
- theory_note: context-profile test: v25 plus non-small fields, same-dist bucket filter, jockey same-surface context, and tighter middle odds in large fields
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v43
- theory_note: context-profile test: v25 plus non-small fields, same-dist bucket filter, jockey same-surface context, and tighter middle odds in large fields
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 26
- tickets: 38
- hits: 5
- total_bet: 3800
- total_payout: 2640
- return_rate: 0.6947
- return_rate_without_max_payout: 0.5026
- return_rate_without_top3_payouts: 0.1868
- axis_top3_rate: 0.5564
- middle_hole_top3_rate: 0.1579
- wide_hit_rate: 0.1316
- average_tickets_per_evaluated_race: 0.0691
- skip_rate: 0.9527
- exclusion_rate: 0.3452
- max_payout: 730
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
- 2025-10-26 05R9 三鷹特別: ['6-7'] payout=730 axis=ゼロスネーク rank=3
- 2025-10-04 08R8 3歳以上2勝クラス: ['10-12'] payout=660 axis=ヴァリディシームス rank=3
- 2025-10-18 08R4 障害3歳以上未勝利: ['5-11'] payout=540 axis=ゴールデンスロープ rank=3
- 2025-10-18 08R9 3歳以上2勝クラス: ['5-13'] payout=440 axis=アンズアメ rank=3
- 2025-12-06 07R10 中京日経賞: ['4-12'] payout=270 axis=ゼットエール rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
