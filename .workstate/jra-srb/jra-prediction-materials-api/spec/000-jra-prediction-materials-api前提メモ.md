# 000-jra-prediction-materials-api 前提メモ

## 0. 要約

- 対象機能名: JRA当日予想材料API
- 改修目的: JRA公式の当日情報と、匿名で無料公開されている対象レースページだけを少数取得し、南関東の prediction bundle に近い予想入力をHTTP APIで返す。
- 現行仕様の要点: JRAは開催・出馬表・オッズ・結果APIまで実装済み。分析APIと一括bundleは未実装。
- 実装時に最も注意すべき点: 「全履歴から算出した精密値」と「当日ページに表示された近走だけから算出したlite値」を混同せず、対象レース結果を予想へ混入させない。
- reference_status: `not_found`
- 実コード優先で採用した判断: 既存の FastAPI → Service → Provider/Extractor、Pydanticモデル、TTLキャッシュ、fixture-firstテストを踏襲する。
- spec_root: `.workstate/jra-srb/jra-prediction-materials-api/spec/`
- progress_root: `.workstate/jra-srb/jra-prediction-materials-api/progress/`
- 実装skillへの主入力: `030-jra-prediction-materials-api実装指示書.md`、`020-jra-prediction-materials-api実装計画書.md`
- ビルド・テスト実行: 本仕様作成フェーズでは実行せず、実装担当または人間へ引き継ぐ。

## 1. 対象

- 対象root: `D:\develop\jra-scr`
- 対象プロジェクト: `jra-srb`
- 関連API: JRA開催、出馬表、オッズ、結果、保存済み結果、南関 prediction bundle

## 2. ユーザー要件

- JRA-VAN/TARGET等の有料データを前提にしない。
- 対象レース当日の少数アクセスで取得できる無料公開情報を使う。
- netkeiba `data_top`、ウマニティ `race_8`、競馬ラボ `umabashira` の匿名公開範囲を候補にする。
- 外部サイトへ大量巡回せず、可能な範囲をJRA向けAPIとして提供する。
- 初期導入時の過去データ一括CLI収集を必須にしない。

## 3. 参照情報

- `project-reference-router` 同梱referenceは.NET系別プロジェクト用であり、本Python/FastAPIプロジェクトに一致しない。
- `reference_status: not_found` とし、reference intakeはスキップした。
- 参照資料: `docs/jra/02_アーキテクチャ.md`、`05_API仕様.md`、`17_nankan_prediction_materials_usage.md`、`27_nankan_prediction_bundle_usage.md`
- 主要コード: `app.py`、`service.py`、`models.py`、`analysis_store.py`、netkeiba provider/service、nankan service/prediction service、代表テスト

## 4. 用語

- `lite`: 対象レースページに匿名公開されている近走範囲だけを母集団にした暫定指標。
- `public source`: ログイン、会員専用Cookie、課金、CAPTCHA回避を必要としない公開ページ。
- `primary component`: JRA公式のcard。取得できなければbundleを成立させない。
- `optional component`: odds、trend、外部分析、lite指標。欠損時もステータス付きでbundleを返す。

## 5. 対象外

- 有料データ、会員専用情報、プレミアム表示値の取得。
- CAPTCHA、アクセス制限、ログイン制御の回避。
- 過去全開催の一括バックフィル。
- 第三者サイトの記事本文、画像、予想文の保存・再配布。
- 機械学習モデルの作成・再学習。

