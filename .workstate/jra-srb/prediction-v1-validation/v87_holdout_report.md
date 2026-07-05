# Prediction Evaluation Report

## 対象
- theory_version: v87
- theory_note: v80 plus ticket filters: exclude middle jockey recent 0.15-0.25 and odds_ratio < 2
- evaluation_period: 2026-01-01..2026-06-28
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v87
- theory_note: v80 plus ticket filters: exclude middle jockey recent 0.15-0.25 and odds_ratio < 2
- evaluation_period: 2026-01-01..2026-06-28
- candidate_races: 1338
- evaluated_races: 1107
- excluded_races: 231
- bet_races: 51
- tickets: 51
- hits: 12
- total_bet: 5100
- total_payout: 6780
- return_rate: 1.3294
- return_rate_without_max_payout: 1.1686
- return_rate_without_top3_payouts: 0.9059
- axis_top3_rate: 0.5574
- middle_hole_top3_rate: 0.3529
- wide_hit_rate: 0.2353
- average_tickets_per_evaluated_race: 0.0461
- skip_rate: 0.9539
- exclusion_rate: 0.1726
- max_payout: 820
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
- 2026-01-25 06R8 4歳以上2勝クラス: ['2-9'] payout=820 axis=ハードセルツァー rank=1
- 2026-01-18 08R3 3歳未勝利: ['7-14'] payout=730 axis=メイショウバルク rank=2
- 2026-03-14 09R2 3歳未勝利: ['8-13'] payout=610 axis=ジューンアゲイン rank=1
- 2026-02-21 09R5 3歳未勝利: ['3-15'] payout=600 axis=フレッチャアズーラ rank=2
- 2026-02-22 10R2 3歳未勝利: ['10-18'] payout=600 axis=ロジケープ rank=1
- 2026-03-22 07R8 4歳以上1勝クラス: ['3-14'] payout=600 axis=エイヘンハールト rank=2
- 2026-01-10 06R2 3歳未勝利: ['2-8'] payout=560 axis=ベルウッドピース rank=1
- 2026-05-09 04R7 4歳以上1勝クラス: ['7-12'] payout=510 axis=ピコテンダー rank=1
- 2026-03-07 06R8 4歳以上1勝クラス: ['3-5'] payout=500 axis=ホークライト rank=1
- 2026-04-26 05R3 3歳未勝利: ['14-16'] payout=470 axis=アニマレイ rank=3

## 採用判断
- decision: promote_release_candidate
- reason: Holdout pass criteria are satisfied.
