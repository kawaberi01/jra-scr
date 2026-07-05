# Prediction Evaluation Report

## 対象
- theory_version: v75
- theory_note: v60 conditional rerank: weaken large-field >10 penalty and disable middle same-dist 0.25-0.35 bonus when axis odds <= 2.0
- evaluation_period: 2026-01-01..2026-06-28
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v75
- theory_note: v60 conditional rerank: weaken large-field >10 penalty and disable middle same-dist 0.25-0.35 bonus when axis odds <= 2.0
- evaluation_period: 2026-01-01..2026-06-28
- candidate_races: 1338
- evaluated_races: 1107
- excluded_races: 231
- bet_races: 183
- tickets: 183
- hits: 22
- total_bet: 18300
- total_payout: 14040
- return_rate: 0.7672
- return_rate_without_max_payout: 0.6497
- return_rate_without_top3_payouts: 0.5432
- axis_top3_rate: 0.5574
- middle_hole_top3_rate: 0.2842
- wide_hit_rate: 0.1202
- average_tickets_per_evaluated_race: 0.1653
- skip_rate: 0.8347
- exclusion_rate: 0.1726
- max_payout: 2150
- live_requests: 0
- cache_dir: .workstate\jra-srb\prediction-v1-validation\netkeiba-cache

## 除外理由
- few_candidates:5: 60
- few_candidates:0: 55
- few_candidates:4: 46
- few_candidates:3: 28
- few_candidates:2: 13
- few_candidates:1: 5
- low_name_match:0/12: 5
- low_name_match:0/16: 3
- low_name_match:1/12: 3
- low_name_match:0/8: 2
- low_name_match:0/10: 1
- low_name_match:0/11: 1
- low_name_match:0/14: 1
- low_name_match:0/15: 1
- low_name_match:1/15: 1
- low_name_match:2/11: 1
- low_name_match:2/12: 1
- low_name_match:3/13: 1
- low_name_match:4/10: 1
- low_name_match:4/16: 1
- low_name_match:5/15: 1

## 的中上位
- 2026-03-21 07R7 4歳以上1勝クラス: ['7-16'] payout=2150 axis=ジェミート rank=1
- 2026-02-28 10R2 3歳未勝利: ['11-13'] payout=1090 axis=ヒッグスボソン rank=2
- 2026-01-25 08R2 3歳未勝利: ['2-16'] payout=860 axis=ドメイン rank=1
- 2026-01-25 06R8 4歳以上2勝クラス: ['2-9'] payout=820 axis=ハードセルツァー rank=1
- 2026-02-10 05R8 4歳以上2勝クラス: ['6-8'] payout=810 axis=ドラゴンテイラー rank=1
- 2026-01-18 08R3 3歳未勝利: ['7-14'] payout=730 axis=メイショウバルク rank=2
- 2026-03-14 09R2 3歳未勝利: ['8-13'] payout=610 axis=ジューンアゲイン rank=1
- 2026-02-21 09R5 3歳未勝利: ['3-15'] payout=600 axis=フレッチャアズーラ rank=2
- 2026-02-22 10R2 3歳未勝利: ['10-18'] payout=600 axis=ロジケープ rank=1
- 2026-03-22 07R8 4歳以上1勝クラス: ['3-14'] payout=600 axis=エイヘンハールト rank=2

## 採用判断
- decision: reject_release_candidate
- reason: ROI 0.7672 < 1.0000; return_rate_without_max_payout 0.6497 < 1.0000
