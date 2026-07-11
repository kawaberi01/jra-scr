# 010-nankan-skill-prediction-flow実装仕様書

## 1. 目的
南関予想スキルの標準フローを、`prediction-bundle` 一発取得を軸に固定し、再取得・再整形・再説明を減らす。

## 2. 対象
- `C:\Users\main\skills\nankan-race-predictor\SKILL.md`
- `C:\Users\main\skills\nankan-race-session-starter\SKILL.md`

## 3. 変更後仕様

### 3.1 同一レースの `prediction-bundle` は 1 回だけ
- 同一の `date/course/race_no/meeting_no/meeting_day` 組では、通常予想中に `prediction-bundle` を再実行しない
- 取得済み bundle を再利用して分析を続ける
- 再取得を許すのは次だけ
  - 最初の取得が `404`
  - 最初の取得が通信失敗や JSON 破損で未成立
  - ユーザーが明示的に再取得や再観測を指示した

### 3.2 bundle 成功後の個別 API 追加取得条件を限定する
- bundle に含まれる `card / odds_summary / trend_context / best_time / closing_speed / pattern / leading_jockeys` は追加で再取得しない
- 個別 API を許可するのは次だけ
  - bundle に該当項目が存在しない
  - 項目はあるが `status` や `usable` 的に不採用で、かつ代替 API が明確
  - 買い目最終確定のために詳細 odds が必要

### 3.3 詳細 odds の追加取得上限
- 標準予想では `odds_summary` を優先し、追加の個別 odds は原則なし
- 追加取得する場合でも、最終候補の組み合わせ 1 から 2 点までに制限する
- 途中の比較や思考整理のためだけに複数組み合わせを広く取得しない

### 3.4 ファイル保存を標準フローから外す
- `uv run jra-srb call-local-api ... > tmp\*.json` のような保存を通常フローで行わない
- CLI が返した整形 JSON をそのまま使う
- 一時ファイル保存を許可するのは、観測や再現のためにユーザーが明示的に求めた場合だけ

### 3.5 JSON 形状前提を固定する
- `pattern` は都度全量探索せず、既知の `runners` 構造から主要指標だけ抜く
- 形状確認のための ad hoc スクリプトは通常予想では走らせない

### 3.6 `trend_context.usable=false` の扱い
- 再取得や再解釈を行わず、不採用理由を短く記載するだけに留める
- `/trend` を事前予想の代替材料として直接採用しない

### 3.7 通常予想と観測実行を分離する
- 通常予想:
  - 中間 JSON を会話へ大量に出さない
  - API 実行ログも最小限
- 観測実行:
  - `取得 API / 成否 / elapsed / fallback 理由` の短いログのみ許可
  - ログのために bundle 再取得を正当化しない

## 4. 対象外
- 予想文面テンプレートの全面改稿
- API エンドポイント仕様の変更
- `dansou-keiba-reference` の仕様変更

## 5. 成功条件
- 同一レースで `prediction-bundle` が 1 回になる
- 標準フローからファイル保存が消える
- `quinella` 等の個別 odds 取得本数が減る
- 中間 JSON や切り分け説明の会話消費が減る
