# Prediction Evaluation Report

## 対象
- theory_version: v70
- theory_note: v60 rerank test: weaken large-field >10 penalty and remove 0.25-0.35 same-dist bonus
- evaluation_period: 2025-07-01..2025-07-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v70
- theory_note: v60 rerank test: weaken large-field >10 penalty and remove 0.25-0.35 same-dist bonus
- evaluation_period: 2025-07-01..2025-07-31
- candidate_races: 288
- evaluated_races: 230
- excluded_races: 58
- bet_races: 54
- tickets: 54
- hits: 8
- total_bet: 5400
- total_payout: 6390
- return_rate: 1.1833
- return_rate_without_max_payout: 0.8611
- return_rate_without_top3_payouts: 0.45
- axis_top3_rate: 0.6
- middle_hole_top3_rate: 0.2778
- wide_hit_rate: 0.1481
- average_tickets_per_evaluated_race: 0.2348
- skip_rate: 0.7652
- exclusion_rate: 0.2014
- max_payout: 1740
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 47
- few_candidates:1: 5
- few_candidates:5: 4
- few_candidates:2: 1
- few_candidates:4: 1

## 的中上位
- 2025-07-20 02R6 3歳未勝利: ['4-7'] payout=1740 axis=ヒットザグラウンド rank=1
- 2025-07-13 03R7 3歳以上1勝クラス: ['3-10'] payout=1200 axis=ビービーエフォート rank=3
- 2025-07-19 03R8 3歳未勝利: ['12-14'] payout=1020 axis=オプレントジュエル rank=3
- 2025-07-27 04R8 出雲崎特別: ['9-12'] payout=890 axis=ノットファウンド rank=1
- 2025-07-20 03R7 3歳未勝利: ['2-9'] payout=440 axis=アイドル rank=1
- 2025-07-06 03R7 3歳未勝利: ['14-16'] payout=420 axis=ウアーシュプルング rank=1
- 2025-07-20 10R3 3歳未勝利: ['10-15'] payout=380 axis=エイシンマールス rank=1
- 2025-07-12 03R4 3歳未勝利: ['3-7'] payout=300 axis=イフルジャンス rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
