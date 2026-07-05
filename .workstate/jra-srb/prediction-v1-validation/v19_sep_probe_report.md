# Prediction Evaluation Report

## 対象
- theory_version: v19
- theory_note: two-middle shape guard: keep v17 rules, but skip standard bets when axis odds <= 4 and odds ratio <= 3
- evaluation_period: 2025-09-01..2025-09-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v19
- theory_note: two-middle shape guard: keep v17 rules, but skip standard bets when axis odds <= 4 and odds ratio <= 3
- evaluation_period: 2025-09-01..2025-09-30
- candidate_races: 240
- evaluated_races: 161
- excluded_races: 79
- bet_races: 117
- tickets: 224
- hits: 26
- total_bet: 22400
- total_payout: 13010
- return_rate: 0.5808
- return_rate_without_max_payout: 0.5259
- return_rate_without_top3_payouts: 0.4348
- axis_top3_rate: 0.5901
- middle_hole_top3_rate: 0.2946
- wide_hit_rate: 0.1161
- average_tickets_per_evaluated_race: 1.3913
- skip_rate: 0.2733
- exclusion_rate: 0.3292
- max_payout: 1230
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 36
- few_candidates:5: 10
- few_candidates:2: 9
- few_candidates:3: 9
- few_candidates:4: 9
- few_candidates:1: 6

## 的中上位
- 2025-09-07 01R10 HTB賞: ['1-12'] payout=1230 axis=コスモアンソロジー rank=2
- 2025-09-14 06R7 3歳未勝利: ['1-7'] payout=1160 axis=ストレートブラック rank=2
- 2025-09-14 09R4 3歳未勝利: ['8-14'] payout=880 axis=ステラノヴァ rank=3
- 2025-09-07 09R7 3歳以上1勝クラス: ['2-4', '2-3'] payout=820 axis=エイユーファイヤー rank=2
- 2025-09-14 09R7 3歳以上1勝クラス: ['1-6'] payout=810 axis=ロンドボス rank=1
- 2025-09-14 06R10 レインボーステークス: ['1-13'] payout=720 axis=アスクナイスショー rank=2
- 2025-09-20 09R9 3歳以上1勝クラス: ['8-16', '8-9'] payout=700 axis=ハクサンアイリス rank=1
- 2025-09-14 06R2 2歳未勝利: ['8-10'] payout=680 axis=フクチャンショウ rank=1
- 2025-09-07 06R7 3歳未勝利: ['6-16'] payout=650 axis=キタノライブリー rank=1
- 2025-09-15 09R6 3歳未勝利: ['2-18'] payout=630 axis=アスクコモンタレヴ rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
