# Prediction Evaluation Report

## 対象
- theory_version: v44
- theory_note: context-profile follow-up: v25 plus same-dist bucket filter, trainer same-distance context, and skip high-rate same-surface jockey buckets
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v44
- theory_note: context-profile follow-up: v25 plus same-dist bucket filter, trainer same-distance context, and skip high-rate same-surface jockey buckets
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 20
- tickets: 28
- hits: 4
- total_bet: 2800
- total_payout: 2240
- return_rate: 0.8
- return_rate_without_max_payout: 0.525
- return_rate_without_top3_payouts: 0.1393
- axis_top3_rate: 0.5564
- middle_hole_top3_rate: 0.1786
- wide_hit_rate: 0.1429
- average_tickets_per_evaluated_race: 0.0509
- skip_rate: 0.9636
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
- 2025-10-18 08R4 障害3歳以上未勝利: ['5-11'] payout=540 axis=ゴールデンスロープ rank=3
- 2025-11-23 05R11 霜月ステークス: ['4-15'] payout=540 axis=ウェイワードアクト rank=1
- 2025-12-14 06R4 障害3歳以上未勝利: ['1-7'] payout=390 axis=ゴールデンスロープ rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
