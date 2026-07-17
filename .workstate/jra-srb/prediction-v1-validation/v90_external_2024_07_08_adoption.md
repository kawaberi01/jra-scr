# v90_summer 2024年7〜8月 外部評価の採否判断

- 理論: v90（評価前に固定）
- 評価期間: 2024-07-01..2024-08-31
- データ監査: PASS（自動パイプラインで評価前に確認）
- decision: reject

## 指標

- 軸馬3着内率: 0.5394
- 回収率: 0.488
- 最大払戻除外回収率: 0.216
- 上位3払戻除外回収率: 0.0
- 買い目数: 25

## 事前固定した判定

- PASS: axis_top3_rate >= 0.45
- FAIL: return_rate >= 1.00
- FAIL: return_rate_without_max_payout >= 1.00
- FAIL: return_rate_without_top3_payouts >= 1.00
- PASS: tickets >= 20

v90の条件はこの外部評価の結果を見て変更しない。rejectの場合、改修は別バージョンで行う。
