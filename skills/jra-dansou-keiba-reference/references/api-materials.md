# API Materials

断層競馬のJRA参考欄では、ローカルAPIだけを利用する。

## 必須

### 1. 予想束

`GET /jra/meetings/{date}/{course}/races/{race_no}/prediction-bundle?meeting_no={meeting_no}&meeting_day={meeting_day}`

確認する項目:

- `card`: 距離、芝ダート、馬場、天候、出走馬
- `odds_summary`: 単勝・ワイドの取得状態
- `trend_context`: 同日先行レースの傾向と取得状態
- `public_analysis`: 公開指数・近走情報の取得状態
- `meta.component_status`: 欠損理由

### 2. 三系統比較

`GET /jra/meetings/{date}/{course}/races/{race_no}/model-comparison?meeting_no={meeting_no}&meeting_day={meeting_day}`

確認する項目:

- `materials_model.ranking`: 当日公開材料の順位と根拠
- `history_model.ranking`: 履歴確率・特徴量寄与
- `v_theory`: V89 / V90 / 対象外、運用状態、単独順位
- `comparison`: 二モデル上位の一致
- `total_evaluation`: 三者順位票の参考集計

## 任意

### 3. 確定後の回顧

結果・払戻APIと保存済み予想評価を使い、断層参考が予想本体を上書きしていなかったかだけを確認する。

## 不足時の扱い

- `history_model.status=unavailable`: 当日公開材料との差は判定しない。
- `v_theory.status=unavailable`: V系の差は判定しない。
- `v_theory.application=summer_shadow`: 参考表示に限定する。
- オッズまたは馬場が未取得: その項目のずれを論じない。
