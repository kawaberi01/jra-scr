# 005-nankan-prediction-summary-api現行仕様整理

## 1. 現行の取得経路
1. `/nankan/.../prediction-bundle` が `NankanPredictionService.get_prediction_bundle()` を呼ぶ。
2. service は card, odds_summary, trend_context, best_time, closing_speed, pattern, leading_jockeys を収集する。
3. 返却モデル `NankanPredictionBundle` は各素材の全量 DTO をそのまま保持する。

## 2. 現行の問題
- `card.runners`
- `pattern.runners[*].categories`
- `best_time.runners`
- `closing_speed.runners`
- `leading_jockeys.items`
- `trend_context.summary`

上記がそのまま返るため、スキル側では大きい JSON を読んだ上で再抽出が必要になる。

## 3. 実コードで確認した制約
- `meeting_no` と `meeting_day` は pattern 取得に必要。
- 予想に必要な主要列は既に bundle 内に揃っている。
- したがって今回は「新しい上流取得」ではなく「bundle -> summary 投影」で十分実装可能。

## 4. trace の現行課題
- `PredictionTraceLogger` は `request_trace_id` を使って `prediction_trace_xxx_<request>.jsonl` へ分割書き込みしている。
- ユーザー運用としては request 単位の別ファイルより、1 ファイルに追記された方が結果確認しやすい。
