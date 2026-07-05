# Prediction Evaluation Report

## 対象
- theory_version: v45
- theory_note: context-profile balance: v25 plus same-dist bucket filter and field-size x middle-odds guard, without trainer-side hard pruning
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v45
- theory_note: context-profile balance: v25 plus same-dist bucket filter and field-size x middle-odds guard, without trainer-side hard pruning
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 44
- tickets: 71
- hits: 11
- total_bet: 7100
- total_payout: 6670
- return_rate: 0.9394
- return_rate_without_max_payout: 0.8042
- return_rate_without_top3_payouts: 0.5563
- axis_top3_rate: 0.5564
- middle_hole_top3_rate: 0.2113
- wide_hit_rate: 0.1549
- average_tickets_per_evaluated_race: 0.1291
- skip_rate: 0.92
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
- 2025-12-20 09R4 障害3歳以上オープン: ['5-13'] payout=960 axis=テイエムマジック rank=1
- 2025-12-07 09R9 豊中特別: ['1-4'] payout=890 axis=タマモキャリコ rank=1
- 2025-11-23 05R7 3歳以上1勝クラス: ['4-14'] payout=870 axis=オウケンシルヴァー rank=2
- 2025-10-26 05R9 三鷹特別: ['6-7'] payout=730 axis=ゼロスネーク rank=3
- 2025-10-04 08R8 3歳以上2勝クラス: ['10-12'] payout=660 axis=ヴァリディシームス rank=3
- 2025-10-12 05R8 3歳以上1勝クラス: ['4-6'] payout=550 axis=アロンズロッド rank=1
- 2025-10-18 08R4 障害3歳以上未勝利: ['5-11'] payout=540 axis=ゴールデンスロープ rank=3
- 2025-10-18 08R9 3歳以上2勝クラス: ['5-13'] payout=440 axis=アンズアメ rank=3
- 2025-12-14 06R4 障害3歳以上未勝利: ['1-7'] payout=390 axis=ゴールデンスロープ rank=1
- 2025-11-16 08R7 3歳以上2勝クラス: ['4-5'] payout=370 axis=ゴールデンクラウド rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
