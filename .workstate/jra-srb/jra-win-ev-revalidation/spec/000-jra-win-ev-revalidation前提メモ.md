# 000-jra-win-ev-revalidation 前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: JRA通常戦の単勝期待値判定の再検証
- 改修目的: 未校正の順位用確率から大穴を自動推奨する状態を止め、時系列検証とライブシャドーを通過した方策だけを購入推奨へ昇格できるようにする。
- 関連API: `GET /jra/meetings/{date}/{course}/races/{race_no}/betting-decision`
- 関連処理: 履歴モデル学習・推論、単勝EV判定、日次スカウト、analysis SQLiteへの予想・結果保存

## 2. 入力情報

- ユーザー要件: 履歴モデル5.41%と単勝133倍から大穴が自動選択された経緯を踏まえ、検証イテレーションを再設計する。
- reference_status: found
- 主reference: `.workstate/jra-srb/jra-win-ev-decision/`
- 補助reference: `.workstate/jra-srb/jra-prediction-model-v2/`、`docs/jra/12_予想エージェント評価プロトコル.md`
- 主要コード: `src/jra_srb/jra_betting_decision.py`、`src/jra_srb/jra_history_model.py`、`src/jra_srb/app.py`
- 主要テスト: `tests/test_jra_betting_decision.py`、履歴モデル関連テスト

## 3. 確認済みの問題

- 履歴モデルartifactは `betting EV is out of scope` と明記している。
- `win_probability_race_normalized` はレース内合計を1にした順位比較値で、単勝購入に使える校正済み勝率ではない。
- 現行方策は `期待回収倍率 → market_edge` の最大値を選ぶため、高オッズ馬を優先しやすい。
- 現行閾値は初期値であり、時系列holdoutによる閾値別検証が未完了である。
- 既存単体テストは数式と分岐を確認するだけで、確率校正・大穴依存・収益再現性を検証していない。
- V89～V117の検証は別理論であり、現行単勝EV方策の採用根拠にはしない。

## 4. 作成する成果物

- `005-jra-win-ev-revalidation現行仕様整理.md`
- `010-jra-win-ev-revalidation実装仕様書.md`
- `020-jra-win-ev-revalidation実装計画書.md`
- `030-jra-win-ev-revalidation実装指示書.md`

## 5. 注意点

- 再検証完了前に通常戦の単勝EVを購入推奨へ戻さない。
- 新馬戦の `newcomer_public_market_consensus` は別方策として分離し、この再検証の学習・採否判定に混ぜない。
- 外部評価期間を見た後に閾値を変更した場合、その期間は外部評価として再利用しない。
- 利益保証ではなく、データリーク防止、確率校正、大穴依存抑制、再現可能な採否判定を目的とする。
