# Prediction Evaluation Report

## 対象
- theory_version: v10
- theory_note: race-confidence follow-up: keep v9 rules, but bet only race 7 or later
- evaluation_period: 2026-01-01..2026-06-28
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v10
- theory_note: race-confidence follow-up: keep v9 rules, but bet only race 7 or later
- evaluation_period: 2026-01-01..2026-06-28
- candidate_races: 1338
- evaluated_races: 1107
- excluded_races: 231
- bet_races: 514
- tickets: 1028
- hits: 99
- total_bet: 102800
- total_payout: 88360
- return_rate: 0.8595
- return_rate_without_max_payout: 0.82
- return_rate_without_top3_payouts: 0.7768
- axis_top3_rate: 0.5158
- middle_hole_top3_rate: 0.3492
- wide_hit_rate: 0.0963
- average_tickets_per_evaluated_race: 0.9286
- skip_rate: 0.5357
- exclusion_rate: 0.1726
- max_payout: 4060
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
- 2026-05-02 08R7 3歳1勝クラス: ['4-12'] payout=4060 axis=ファニーバニー rank=3
- 2026-04-26 03R12 4歳以上1勝クラス: ['5-13'] payout=2290 axis=レジェンダリーデイ rank=3
- 2026-02-22 10R10 和布刈特別: ['11-15'] payout=2160 axis=スマートスピア rank=2
- 2026-04-26 03R11 モルガナイトステークス: ['6-13'] payout=2100 axis=サウンドモリアーナ rank=1
- 2026-03-01 09R12 4歳以上2勝クラス: ['6-14'] payout=1890 axis=ランスオブセヘル rank=3
- 2026-06-28 03R12 3歳以上1勝クラス[指定]: ['1-8'] payout=1880 axis=ロイヤルスパイア rank=3
- 2026-01-04 08R11 スポーツニッポン賞京都金杯: ['11-15'] payout=1870 axis=ブエナオンダ rank=1
- 2026-01-12 06R9 成田特別: ['2-10'] payout=1770 axis=オオタチ rank=3
- 2026-04-12 06R12 4歳以上1勝クラス: ['1-2'] payout=1720 axis=ハーモニーソング rank=2
- 2026-04-19 03R8 4歳以上1勝クラス: ['11-13'] payout=1710 axis=オウケンシルヴァー rank=2

## 採用判断
- decision: reject_release_candidate
- reason: ROI 0.8595 < 1.0000; return_rate_without_max_payout 0.8200 < 1.0000
