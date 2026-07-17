# Prediction Evaluation Report

## 対象
- theory_version: v265
- theory_note: fast-pace top3 suitability bonus 2.0
- evaluation_period: 2025-11-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v265
- theory_note: fast-pace top3 suitability bonus 2.0
- evaluation_period: 2025-11-01..2025-12-31
- candidate_races: 576
- evaluated_races: 444
- excluded_races: 132
- bet_races: 142
- tickets: 142
- hits: 17
- total_bet: 14200
- total_payout: 10050
- return_rate: 0.7077
- return_rate_without_max_payout: 0.6282
- return_rate_without_top3_payouts: 0.5035
- axis_top3_rate: 0.2477
- middle_hole_top3_rate: 0.2606
- wide_hit_rate: 0.1197
- average_tickets_per_evaluated_race: 0.3198
- skip_rate: 0.6802
- exclusion_rate: 0.2292
- max_payout: 1130
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:0: 84
- few_candidates:5: 22
- few_candidates:4: 13
- few_candidates:3: 8
- few_candidates:1: 3
- few_candidates:2: 2

## 的中上位
- 2025-12-14 07R6 3歳以上1勝クラス: ['11-18'] payout=1130 axis=テンミラクルスター rank=1
- 2025-12-06 06R11 スポーツニッポン賞ステイヤーズステークス: ['4-7'] payout=980 axis=クロミナンス rank=3
- 2025-11-09 05R8 3歳以上2勝クラス: ['5-6'] payout=790 axis=アンズアメ rank=1
- 2025-11-15 05R11 武蔵野ステークス: ['1-4'] payout=700 axis=コスタノヴァ rank=2
- 2025-12-06 09R10 妙見山ステークス: ['2-14'] payout=700 axis=ゲッティヴィラ rank=2
- 2025-11-01 05R6 3歳以上1勝クラス: ['4-14'] payout=670 axis=セギレエルビエント rank=1
- 2025-11-29 05R8 3歳以上2勝クラス: ['4-7'] payout=660 axis=ジェイエルマスター rank=3
- 2025-11-09 03R2 2歳未勝利: ['10-15'] payout=560 axis=アンジュプロミス rank=1
- 2025-11-23 08R7 3歳以上1勝クラス: ['1-7'] payout=560 axis=ロットブラータ rank=3
- 2025-11-23 05R11 霜月ステークス: ['4-15'] payout=540 axis=ウェイワードアクト rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
