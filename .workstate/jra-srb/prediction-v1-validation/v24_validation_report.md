# Prediction Evaluation Report

## 対象
- theory_version: v24
- theory_note: target-feature test: keep v23 rules, and require selected middles to have abs weight diff <= 8
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v24
- theory_note: target-feature test: keep v23 rules, and require selected middles to have abs weight diff <= 8
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 394
- tickets: 762
- hits: 122
- total_bet: 76200
- total_payout: 82860
- return_rate: 1.0874
- return_rate_without_max_payout: 1.0564
- return_rate_without_top3_payouts: 1.0064
- axis_top3_rate: 0.5564
- middle_hole_top3_rate: 0.2835
- wide_hit_rate: 0.1601
- average_tickets_per_evaluated_race: 1.3855
- skip_rate: 0.2836
- exclusion_rate: 0.3452
- max_payout: 2360
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
- 2025-12-07 07R2 3歳以上1勝クラス: ['11-16'] payout=2360 axis=アクアマリーナ rank=3
- 2025-11-23 05R12 3歳以上2勝クラス: ['10-12', '8-10'] payout=2290 axis=ミクストベリーズ rank=3
- 2025-12-06 09R8 3歳以上2勝クラス: ['8-10'] payout=2090 axis=ペイシャケイプ rank=3
- 2025-11-09 08R11 みやこステークス: ['5-12'] payout=1720 axis=ダブルハートボンド rank=1
- 2025-11-02 08R12 3歳以上2勝クラス: ['4-6'] payout=1460 axis=ロンドボス rank=2
- 2025-11-24 03R10 五色沼特別: ['1-6'] payout=1380 axis=コンドゥイア rank=2
- 2025-11-15 08R10 アンドロメダステークス: ['9-16'] payout=1350 axis=シェイクユアハート rank=2
- 2025-10-18 08R11 トルマリンステークス: ['6-9'] payout=1340 axis=パルクリチュード rank=2
- 2025-12-20 07R2 3歳以上1勝クラス: ['9-15'] payout=1280 axis=モリノアミーゴ rank=1
- 2025-10-13 05R7 3歳以上1勝クラス: ['7-16'] payout=1230 axis=タマモトリノ rank=2

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
