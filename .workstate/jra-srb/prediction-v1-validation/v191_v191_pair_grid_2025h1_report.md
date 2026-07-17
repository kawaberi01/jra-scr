# Prediction Evaluation Report

## 対象
- theory_version: v191
- theory_note: pair-direct: middle weight change at most 1
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v191
- theory_note: pair-direct: middle weight change at most 1
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 56
- tickets: 56
- hits: 4
- total_bet: 5600
- total_payout: 3380
- return_rate: 0.6036
- return_rate_without_max_payout: 0.4339
- return_rate_without_top3_payouts: 0.1357
- axis_top3_rate: 0.0712
- middle_hole_top3_rate: 0.1429
- wide_hit_rate: 0.0714
- average_tickets_per_evaluated_race: 0.0664
- skip_rate: 0.9336
- exclusion_rate: 0.5119
- max_payout: 950
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
- 2025-05-25 05R8 三峰山特別: ['1-3'] payout=950 axis=エーリアル rank=3
- 2025-06-15 05R10 江の島ステークス: ['1-2'] payout=860 axis=カフェグランデ rank=1
- 2025-03-08 06R10 上総ステークス: ['2-15'] payout=810 axis=ロードクロンヌ rank=1
- 2025-03-02 06R12 4歳以上2勝クラス: ['5-10'] payout=760 axis=ノットファウンド rank=2

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
