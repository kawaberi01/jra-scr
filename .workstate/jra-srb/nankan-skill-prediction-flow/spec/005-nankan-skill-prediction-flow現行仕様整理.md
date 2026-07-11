# 005-nankan-skill-prediction-flow現行仕様整理

## 1. 現行の明文化済みルール

### 1.1 predictor 側
`nankan-race-predictor` では次が定義済み。
- 事前予想では `prediction-bundle` を優先する
- `meeting_no` と `meeting_day` を付ける
- 開催中は `refresh=true` を付ける
- `404` なら個別 API へフォールバックしてよい
- `odds_summary` は主材料として使い、詳細オッズは必要時だけ追加取得する
- `trend_context` は `usable=true` のときだけ採用する
- `pattern` は主要指標だけ抜く

### 1.2 starter 側
`nankan-race-session-starter` では次が既定化されている。
- 1 レースだけ扱う
- `prediction-bundle` 優先
- live 中は `refresh=true`
- `404` でも個別 API フォールバック可

## 2. 現行仕様の弱い点

### 2.1 bundle 再取得禁止が書かれていない
- 「優先する」はあるが、「同一レースで 1 回だけ」がない
- 結果として会話中の途中確認や別視点整理で再取得が入り得る

### 2.2 bundle 成功後の個別 API 追加条件が広い
- `odds_summary` だけでは足りないと感じた時の歯止めが弱い
- `leading_jockeys` や `trend_context` も bundle にあるのに、追加確認へ寄りやすい

### 2.3 ファイル保存禁止が書かれていない
- 標準出力の整形 JSON をそのまま使う原則はある
- ただし `> tmp\*.json` を挟んではいけない、とは書かれていない
- そのため空ファイル、UTF-16、読み戻し失敗のような枝が生まれる

### 2.4 JSON 形状前提が弱い
- `pattern` は主要指標だけ抜くとはある
- しかし `pattern.runners` 前提で扱うこと、都度形状探索しないことが書かれていない

### 2.5 観測モードと通常モードが分かれていない
- 通常予想でも途中経過や JSON 処理の切り分けを会話へ出しやすい
- これが時間・トークンの両方を押し上げる

## 3. 観測結果との対応
- API trace: 同一 race の `prediction-bundle` 2 回
- 実行メッセージ: `prediction-bundle` 保存 -> 空ファイル判定 -> エンコード切り分け -> 形状再確認
- 実行メッセージ: `quinella` の個別オッズ取得

## 4. 仕様差分の方向
- 「bundle 優先」から「bundle 再取得禁止」へ強化する
- 「必要時だけ追加取得」を、許可条件と上限本数で具体化する
- 「CLI の JSON をそのまま使う」を、ファイル保存禁止まで含めて明文化する
- 観測実行だけ例外的に短い実行ログを許可する
