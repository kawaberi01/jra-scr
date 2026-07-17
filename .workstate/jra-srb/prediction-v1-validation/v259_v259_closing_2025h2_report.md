# Prediction Evaluation Report

## 対象
- theory_version: v259
- theory_note: distance-normalized closing speed bonus 10.0
- evaluation_period: 2025-07-01..2025-10-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v259
- theory_note: distance-normalized closing speed bonus 10.0
- evaluation_period: 2025-07-01..2025-10-31
- candidate_races: 1152
- evaluated_races: 816
- excluded_races: 336
- bet_races: 229
- tickets: 229
- hits: 45
- total_bet: 22900
- total_payout: 24940
- return_rate: 1.0891
- return_rate_without_max_payout: 1.0459
- return_rate_without_top3_payouts: 0.9672
- axis_top3_rate: 0.2978
- middle_hole_top3_rate: 0.345
- wide_hit_rate: 0.1965
- average_tickets_per_evaluated_race: 0.2806
- skip_rate: 0.7194
- exclusion_rate: 0.2917
- max_payout: 990
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 290
- few_candidates:1: 30
- few_candidates:2: 9
- few_candidates:3: 3
- few_candidates:5: 3
- few_candidates:4: 1

## 的中上位
- 2025-08-10 07R7 CBC賞: ['9-17'] payout=990 axis=ジューンブレア rank=2
- 2025-10-04 08R10 大山崎ステークス: ['9-15'] payout=910 axis=ルディック rank=2
- 2025-07-27 04R8 出雲崎特別: ['9-12'] payout=890 axis=ノットファウンド rank=1
- 2025-08-16 01R6 3歳未勝利: ['1-13'] payout=810 axis=メイショウゲキハ rank=2
- 2025-10-18 08R11 トルマリンステークス: ['5-9'] payout=810 axis=レイナデアルシーラ rank=1
- 2025-07-26 04R11 3歳以上1勝クラス: ['3-8'] payout=780 axis=ウアーシュプルング rank=3
- 2025-10-05 08R10 藤森ステークス: ['4-12'] payout=720 axis=スターターン rank=3
- 2025-07-27 01R3 3歳未勝利: ['11-12'] payout=710 axis=オンクラウドナイン rank=3
- 2025-08-17 01R7 3歳以上1勝クラス: ['2-5'] payout=710 axis=ピコローズ rank=1
- 2025-09-20 06R7 3歳以上1勝クラス: ['5-6'] payout=700 axis=ルールーリマ rank=3

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
