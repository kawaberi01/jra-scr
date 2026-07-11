---
name: jra-race-predictor
description: Predict JRA races from the local same-day API with explicit rationale, odds-aware tickets, persistence, and post-race evaluation. Use for JRA race predictions, rankings, betting suggestions, or result comparisons.
---

# JRA Race Predictor

南関 `nankan-race-predictor` の出力順と判断枠組みをJRA用に適合したスキルです。公開・匿名データだけを使い、取得不能項目は推測で埋めません。

## 手順

1. 日付、場、レース番号、開催回、開催日を特定する。
2. モード未指定なら `総合買い目型` を既定とする。
3. 発走前は次を取得する。
   - `GET /jra/meetings/{date}/{course}/races/{race_no}/prediction-bundle?meeting_no=...&meeting_day=...&refresh=true`
   - 履歴モデルの成果物が利用可能なら、`GET /jra/meetings/{date}/{course}/races/{race_no}/model-comparison?meeting_no=...&meeting_day=...&refresh=true`
   - 買い目を検討する場合は、`GET /jra/meetings/{date}/{course}/races/{race_no}/betting-decision?meeting_no=...&meeting_day=...&budget=...&refresh=true` を使う。
4. `card`、`odds_summary`、`trend_context`、`public_analysis`、3種の lite 指標と、比較APIの両モデル順位を確認する。
5. `component_status` と取得日時を明記する。Umanity会員限定欄などは `unavailable` のまま扱う。
6. 頭候補、軸候補、相手候補を分け、順位と各馬の根拠を出す。
7. `betting_decision.status=recommended` のときだけ、返却された単勝買い目を使う。`no_bet` または `unavailable` なら順位のみを出し、買い目を作らない。
8. 予想を保存する場合は `prediction_id`、予想時点束、順位、買い目を analysis SQLite に保存する。
9. 確定後だけJRA結果・払戻を取得・保存し、保存済み予想を評価する。未確定なら評価しない。

## 二モデルの扱い

- 公開材料モデルは当日オッズ・公式情報・公開分析を使う。履歴モデルは対象日前日までの確定結果だけを使う。
- `top3_agreement` は強調材料にするが、二つの確率を合算した順位はまだ出さない。統合係数は別途シャドー評価で決める。
- 上位が食い違う場合は、馬番・両者の順位・履歴モデルの特徴量寄与を示し、当日情報またはオッズに理由があるか確認する。
- `history_model.status=unavailable` のときは公開材料モデルのみで予想し、履歴モデルの値を補完しない。
- 単勝期待値判定は履歴モデルのレース内正規化勝率と単勝オッズを比較する。ワイド・馬連・三連系は共同確率が未実装のため自動提案しない。

## 評価の優先順

1. JRA公式の出馬表、馬場、馬体重、当日オッズ
2. Keibalab匿名公開のΩ指数・近5走
3. netkeiba匿名公開のコース分析
4. JRA公式の同日先行レース傾向
5. 近走から作る持ち時計・上がり・脚質 lite

公開外部データは補正材料です。JRA公式と矛盾するときはJRA公式を優先します。2歳戦・新馬戦では近走指標の比重を落とします。

## 固定出力

次の順を維持します。

1. `レース情報`
2. `予想モード`
3. `取得時点・データ状態`
4. `使用データと欠損`
5. `当日傾向`
6. `熱さ判定`
7. `予想順位`
8. `予想の根拠`
9. `買い方`
10. `予算別の買い方`（1000円 / 2000円 / 3000円）
11. `マークシート向け`
12. `注意点`
13. `結果検証`（確定後のみ）

## 状態ルール

- 発走前: `事前予想` と記録する。
- 発走後に初めて作った順位は `回顧参考` とし、事前予想として評価しない。
- 結果0件、払戻0件、または確定表示が確認できない場合は `未確定` とする。
- 同日傾向は対象レースより前の確定レースだけを使う。
- キャッシュ再利用時は `cache_hit` を確認し、再観測を求められた場合だけ `refresh=true` を使う。

## モード

- `integrated_betting`: 総合買い目型（既定）
- `conservative`: 堅実型。複勝・ワイド・馬連寄り
- `value_focus`: 妙味重視型。公開評価と市場支持のずれを見る
- `aggressive_combo`: 攻め型。軸が明確な場合だけ三連系

`熱い！` は公式材料、市場支持、近走補正、相手の絞りやすさが複数一致するときだけ使います。
