# 030-nankan-skill-prediction-flow実装指示書

## 1. 目的
`nankan-race-predictor` と `nankan-race-session-starter` の運用文を修正し、通常予想の取得フローを縮める。

## 2. 変更してよい範囲
- `C:\Users\main\skills\nankan-race-predictor\SKILL.md`
- `C:\Users\main\skills\nankan-race-session-starter\SKILL.md`

## 3. 変更してはいけない範囲
- API 実装
- 予想テンプレート本文の全面変更
- 他スキルの仕様変更

## 4. 実装順序
1. predictor に `prediction-bundle` 1 回固定ルールを追加
2. predictor に bundle 成功後の追加取得制限を追加
3. predictor にファイル保存禁止と `pattern.runners` 前提を追加
4. predictor に通常予想 / 観測実行の分離ルールを追加
5. starter に同方針を短く反映
6. 文面の矛盾を見直す

## 5. 実装詳細

### 5.1 predictor に必ず入れる文言
- 同一レースの `prediction-bundle` は通常予想で 1 回だけ取得する
- 成功した bundle を理由なく再取得しない
- `404`、取得失敗、ユーザー明示指示のときだけ再取得または個別フォールバックを許可する
- bundle に含まれる項目は、成功後に個別 API で再取得しない
- 詳細 odds の追加取得は最終候補 1 から 2 点まで
- 通常予想では API 結果をファイル保存しない
- `pattern` は `runners` から主要指標だけ抜く
- 通常予想では中間 JSON や長い途中経過を会話へ出さない
- 観測時だけ短い実行ログを許可する

### 5.2 starter に必ず入れる文言
- 1 レース中の `prediction-bundle` は 1 回だけ
- live 中でも再取得は自動で繰り返さない
- `404` 時だけ通常フォールバック可
- 通常フローでは保存・再読込を挟まない

## 6. テスト観点
- 文面上、標準フローで `> tmp\*.json` を誘発しないこと
- 文面上、bundle 成功後の `best-time` / `closing-speed` / `trend-context` / `leading_jockeys` 再取得を誘発しないこと
- 文面上、個別 quinella 追加取得が常態化しないこと

## 7. 人手確認観点
- 次回の 1 レース予想で、途中メッセージに保存切り分けや形状探索が出ないか
- trace で `prediction-bundle` が 1 回になっているか
- 追加 odds 本数が減っているか

## 8. 禁止事項
- 曖昧な表現のまま `必要に応じて` を多用しない
- 観測用ルールを通常予想に混ぜない
- 新しい例外経路を増やし過ぎない
