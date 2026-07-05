# Prediction Evaluation Report

## 対象
- theory_version: v52
- theory_note: targeted-guard test: v49 plus axis popularity <= 2 only
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v52
- theory_note: targeted-guard test: v49 plus axis popularity <= 2 only
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 300
- tickets: 558
- hits: 83
- total_bet: 55800
- total_payout: 52560
- return_rate: 0.9419
- return_rate_without_max_payout: 0.9179
- return_rate_without_top3_payouts: 0.8763
- axis_top3_rate: 0.6036
- middle_hole_top3_rate: 0.2849
- wide_hit_rate: 0.1487
- average_tickets_per_evaluated_race: 1.0145
- skip_rate: 0.4545
- exclusion_rate: 0.3452
- max_payout: 1340
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
- 2025-10-18 08R11 トルマリンステークス: ['6-9'] payout=1340 axis=パルクリチュード rank=2
- 2025-10-13 05R7 3歳以上1勝クラス: ['7-16'] payout=1230 axis=タマモトリノ rank=2
- 2025-12-06 09R10 妙見山ステークス: ['2-14', '14-15'] payout=1230 axis=ゲッティヴィラ rank=2
- 2025-10-05 08R9 大原ステークス: ['1-3', '1-9'] payout=1090 axis=レディーヴァリュー rank=1
- 2025-12-14 07R7 3歳以上1勝クラス: ['12-13'] payout=1090 axis=トーアケルキラ rank=2
- 2025-11-02 05R10 秋嶺ステークス: ['5-11'] payout=1080 axis=エコロアゼル rank=1
- 2025-10-11 05R12 3歳以上1勝クラス: ['3-8'] payout=1070 axis=トニケンサンバ rank=3
- 2025-11-16 03R8 3歳以上1勝クラス: ['6-13'] payout=1060 axis=ディニトーソ rank=1
- 2025-12-06 07R7 3歳以上1勝クラス: ['14-15'] payout=1060 axis=ホウオウサムレット rank=3
- 2025-12-06 07R11 飛騨ステークス: ['6-9'] payout=1060 axis=レディマリオン rank=1

## 採用判断
- decision: needs_more_test
- reason: Validation metrics were checked, but holdout has not been run yet.
