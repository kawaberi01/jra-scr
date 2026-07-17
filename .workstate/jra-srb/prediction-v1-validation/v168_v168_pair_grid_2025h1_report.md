# Prediction Evaluation Report

## 対象
- theory_version: v168
- theory_note: pair-direct: odds ratio at most 5
- evaluation_period: 2025-01-01..2025-06-30
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v168
- theory_note: pair-direct: odds ratio at most 5
- evaluation_period: 2025-01-01..2025-06-30
- candidate_races: 1727
- evaluated_races: 843
- excluded_races: 884
- bet_races: 164
- tickets: 164
- hits: 14
- total_bet: 16400
- total_payout: 9020
- return_rate: 0.55
- return_rate_without_max_payout: 0.4835
- return_rate_without_top3_payouts: 0.3835
- axis_top3_rate: 0.1684
- middle_hole_top3_rate: 0.2439
- wide_hit_rate: 0.0854
- average_tickets_per_evaluated_race: 0.1945
- skip_rate: 0.8055
- exclusion_rate: 0.5119
- max_payout: 1090
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
- 2025-06-15 05R6 3歳以上1勝クラス: ['1-5'] payout=1090 axis=プレシャスデイ rank=2
- 2025-06-15 05R10 江の島ステークス: ['1-2'] payout=860 axis=カフェグランデ rank=1
- 2025-02-08 05R12 4歳以上1勝クラス: ['14-15'] payout=780 axis=マケズギライ rank=1
- 2025-04-27 05R8 4歳以上2勝クラス: ['2-10'] payout=770 axis=シンバーシア rank=1
- 2025-02-23 08R11 大和ステークス: ['9-13'] payout=760 axis=ドンアミティエ rank=1
- 2025-05-25 08R10 高瀬川ステークス: ['2-13'] payout=610 axis=キャプテンネキ rank=1
- 2025-02-01 05R9 白嶺ステークス: ['6-8'] payout=600 axis=サクラトップリアル rank=2
- 2025-04-12 03R8 4歳以上1勝クラス: ['7-16'] payout=550 axis=カエルム rank=1
- 2025-05-18 05R11 ヴィクトリアマイル: ['16-17'] payout=550 axis=アスコリピチェーノ rank=1
- 2025-04-13 03R6 4歳以上1勝クラス: ['2-6'] payout=530 axis=ソルレース rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
