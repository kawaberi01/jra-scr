# Prediction Evaluation Report

## 対象
- theory_version: v2
- theory_note: axis-quality test: reduce recent top3 volatility and penalize poor recent average rank more strongly
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v2
- theory_note: axis-quality test: reduce recent top3 volatility and penalize poor recent average rank more strongly
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 535
- tickets: 1019
- hits: 105
- total_bet: 101900
- total_payout: 92410
- return_rate: 0.9069
- return_rate_without_max_payout: 0.8762
- return_rate_without_top3_payouts: 0.8192
- axis_top3_rate: 0.4345
- middle_hole_top3_rate: 0.2365
- wide_hit_rate: 0.103
- average_tickets_per_evaluated_race: 1.8527
- skip_rate: 0.0273
- exclusion_rate: 0.3452
- max_payout: 3130
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
- 2025-10-04 08R7 3歳以上1勝クラス: ['6-16'] payout=3130 axis=セディバン rank=3
- 2025-12-14 09R8 3歳以上2勝クラス: ['7-8'] payout=2910 axis=クーデール rank=1
- 2025-10-25 04R12 3歳以上1勝クラス: ['6-10'] payout=2890 axis=ワタシマツワ rank=1
- 2025-10-18 04R10 妙高特別: ['5-10', '10-12'] payout=2700 axis=ファムエレガンテ rank=1
- 2025-12-20 06R11 ターコイズステークス: ['1-5'] payout=2570 axis=ソルトクィーン rank=3
- 2025-12-20 07R6 3歳以上1勝クラス: ['10-12'] payout=2510 axis=カスバートテソーロ rank=2
- 2025-12-06 09R8 3歳以上2勝クラス: ['8-10'] payout=2090 axis=ペイシャケイプ rank=3
- 2025-12-13 09R4 障害3歳以上未勝利: ['9-12'] payout=2090 axis=ハイウェイスター rank=3
- 2025-11-30 05R8 ベゴニア賞: ['3-8'] payout=1850 axis=コルテオソレイユ rank=2
- 2025-12-06 06R8 イルミネーションジャンプステークス: ['1-4'] payout=1780 axis=ホウオウエクレール rank=3

## 採用判断
- decision: needs_more_test
- reason: validationのprimary metricsを確認したが、holdout未実行のため昇格判断はしない。
