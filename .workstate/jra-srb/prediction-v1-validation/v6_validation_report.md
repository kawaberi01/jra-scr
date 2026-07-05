# Prediction Evaluation Report

## 対象
- theory_version: v6
- theory_note: ticket-count robustness test: keep v4 rules, but buy only the top middle candidate
- evaluation_period: 2025-10-01..2025-12-31
- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed
- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period

## ルール
- axis_rule: target race dateより前の過去走スコア最大馬
- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭
- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race
- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions

## 集計
- theory_version: v6
- theory_note: ticket-count robustness test: keep v4 rules, but buy only the top middle candidate
- evaluation_period: 2025-10-01..2025-12-31
- candidate_races: 840
- evaluated_races: 550
- excluded_races: 290
- bet_races: 503
- tickets: 503
- hits: 60
- total_bet: 50300
- total_payout: 48470
- return_rate: 0.9636
- return_rate_without_max_payout: 0.9125
- return_rate_without_top3_payouts: 0.8342
- axis_top3_rate: 0.4964
- middle_hole_top3_rate: 0.2545
- wide_hit_rate: 0.1193
- average_tickets_per_evaluated_race: 0.9145
- skip_rate: 0.0855
- exclusion_rate: 0.3452
- max_payout: 2570
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
- 2025-12-20 06R11 ターコイズステークス: ['1-5'] payout=2570 axis=リラボニート rank=2
- 2025-12-06 09R8 3歳以上2勝クラス: ['8-10'] payout=2090 axis=ペイシャケイプ rank=3
- 2025-11-30 05R8 ベゴニア賞: ['3-8'] payout=1850 axis=コルテオソレイユ rank=2
- 2025-11-09 08R11 みやこステークス: ['5-12'] payout=1720 axis=ダブルハートボンド rank=1
- 2025-10-19 04R6 3歳以上1勝クラス: ['5-11'] payout=1640 axis=ダイシンレアレア rank=3
- 2025-11-24 03R10 五色沼特別: ['1-6'] payout=1380 axis=コンドゥイア rank=2
- 2025-11-15 08R10 アンドロメダステークス: ['9-16'] payout=1350 axis=シェイクユアハート rank=2
- 2025-10-18 08R11 トルマリンステークス: ['6-9'] payout=1340 axis=パルクリチュード rank=2
- 2025-12-20 09R11 タンザナイトステークス: ['5-14'] payout=1300 axis=ヤブサメ rank=3
- 2025-10-13 05R7 3歳以上1勝クラス: ['7-16'] payout=1230 axis=タマモトリノ rank=2

## 採用判断
- decision: needs_more_test
- reason: validationのprimary metricsを確認したが、holdout未実行のため昇格判断はしない。
