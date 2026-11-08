---
name: nankan-race-session-complete
description: "Complete a one-race Nankan session in a single thread: produce the pre-race prediction, persist the structured prediction to analysis SQLite, fetch and persist the official result, then evaluate the saved prediction into evaluations. Use when the user wants one session per race with DB persistence for predictions and evaluations, not prediction text only."
---

# Nankan Race Session Complete

1セッションで1レースを扱い、予想から結果振り返り、`predictions` / `evaluations` 保存まで完結させる skill です。

予想・結果のローカル API を使う前に [local-race-api-ready](../local-race-api-ready/SKILL.md) を実行する。同じ作業で準備済みなら再実行せず、失敗したら API 依存の処理に進まない。

予想だけ返す `nankan-race-session-starter` とは役割が異なります。  
この skill は、会話の中で確定した予想内容と買い目を、構造化して DB に残すことを目的にします。

## 使う場面

- ユーザーが「予想して、結果も見て、振り返ってDBに入れて」のように、1レース完結を望むとき
- セッションごとに 1 レースの `predictions` / `evaluations` を残したいとき
- 日次ログではなく、構造化テーブルを主としたいとき

## 使わない場面

- 予想本文だけ返せばよいとき
  - この場合は `nankan-race-session-starter` を使う
- 結果だけ `race_results` / `result_entries` / `payouts` に保存したいとき
  - この場合は `nankan-result-save-to-analysis-sqlite` を使う

## 完結フロー

1. 対象レースを 1 件に固定する
2. 予想本文は `nankan-race-predictor` の流儀で作る
3. 予想を確定したら、その場で `predictions` / `prediction_tickets` を保存する
4. 結果要求が来たら、まず `nankan-result-save-to-analysis-sqlite` と同等の流れで結果を保存する
5. 保存済み `prediction_tickets` と DB の払戻を使って `evaluations` / `evaluation_ticket_results` を保存する
6. 結果照合時は、`nankan-race-predictor` の `買い方の結果（結果確定後の固定テンプレート）` に従い、買い目ごとの予想時点の倍率・取得時刻と回収率を必ず返す

## 保存方針

- 予想時点の材料だけを `pre_race_snapshot_json` に入れる。評価対象の買い目ごとに、予想時点の倍率（オッズ）、取得時刻、取得元または `未取得` も残す
- `prediction_json` は会話で確定した順位、買い目、注意点を主に保存する
- `prediction_tickets` は、そのセッションで評価対象にする買い目案を保存する
  - 原則として `1000円案` を評価対象の既定にする
- `evaluations` は、保存済み `prediction_tickets` と DB の払戻から決定的に計算する。会話で示す回収率は `合計確定払戻 ÷ 合計購入額 × 100` とし、小数第1位まで表示する
- 実買い記録が別にある場合は、それは `bet_records` 系で扱い、ここでは混ぜない

## 既定の評価対象

- 予算別買い方が複数あっても、既定では `1000円案` を `prediction_tickets` として保存する
- ユーザーが明示すれば `2000円案` や `3000円案` を保存してよい
- どの案を保存したかは、`prediction_json` と会話の両方に明記する
- 結果照合時は、予想時点の倍率が未取得の買い目を推測で埋めない。`未取得` と確定払戻を並べて表示する

## 実行コマンド

予想保存:

```powershell
uv run python "C:\Users\main\skills\nankan-race-session-complete\scripts\save_nankan_prediction_to_analysis_sqlite.py" --input ".\tmp\prediction_payload.json"
```

評価保存:

```powershell
uv run python "C:\Users\main\skills\nankan-race-session-complete\scripts\evaluate_saved_prediction_to_analysis_sqlite.py" --input ".\tmp\evaluation_payload.json"
```

`--input` を省略した場合は標準入力 JSON を使ってよい。

## 入力 JSON の最小要件

### 予想保存

```json
{
  "prediction_id": "pred-...",
  "race_id": "2026070921040410",
  "theory_version": "nankan-race-predictor:integrated_betting:assistant_thread:v1",
  "mode": "integrated_betting",
  "budget": 1000,
  "pre_race_snapshot": {},
  "prediction_json": {},
  "prediction_tickets": []
}
```

### 評価保存

```json
{
  "prediction_id": "pred-...",
  "evaluation_id": "eval-...",
  "review": {},
  "review_notes": []
}
```

## 注意

- 1セッションで複数レースを混ぜない
- `predictions` 保存前に結果を見ない
- `evaluations` は必ず保存済み `prediction_tickets` を基準に計算する
- 日次ログは補助。主記録は `predictions` / `evaluations`
