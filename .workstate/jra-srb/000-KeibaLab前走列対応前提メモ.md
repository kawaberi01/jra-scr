# 000-KeibaLab前走列対応前提メモ

## 1. 対象
- 対象 root: `D:\develop\jra-scr`
- 対象機能: KeibaLab 馬柱の前走情報解析
- 改修目的: 初出走など前走欄が空の馬が含まれても、各馬番へ正しい前走情報だけを紐付ける。
- 関連 API: `GET /jra/meetings/{date}/{course}/races/{race_no}/prediction-bundle`、`model-comparison`、`betting-decision`

## 2. 入力情報
- ユーザー要件: 外部馬柱の解析不具合を直すための仕様を作成する。
- reference_status: 外部 reference なし。実取得 HTML と実コードを根拠にする。
- 参照した既存資料: `skills/jra-race-predictor/SKILL.md`
- 参照した主要コード:
  - `src/jra_srb/jra_public_analysis_extractors.py`
  - `src/jra_srb/jra_prediction_materials.py`
  - `src/jra_srb/jra_prediction_engine.py`
  - `tests/test_jra_prediction_materials.py`
- 実取得確認: KeibaLab の 2026-07-12 福島3R 馬柱で、14番スティールシップは「初出走」と表示される一方、現行 API は別馬由来の前走を14番へ付与した。

## 3. 作成する成果物
- `005-KeibaLab前走列対応現行仕様整理.md`
- `010-KeibaLab前走列対応実装仕様書.md`
- `020-KeibaLab前走列対応実装計画書.md`
- `030-KeibaLab前走列対応実装指示書.md`

## 4. 注意点
- 今回は解析の列対応だけを修正対象とする。予想モデルの再学習、期待値ロジックの調整、既存保存済み予想の再計算は対象外とする。
- 初出走はエラーではない。`recent_races=[]` を正しい正常値として保持する。
- fixture は初出走と前走ありの馬が混在する実構造を再現し、空欄列を削除しないことを検証する。
