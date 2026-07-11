# 030-jra-prediction-materials-api 実装指示書

## 1. 対象概要

- 対象機能: JRA当日予想材料API
- 改修目的: 事前一括収集を必須にせず、当日のJRA公式情報と3サイトの匿名公開レースページを少数取得して予想材料APIを提供する。
- この機能が行う処理: source key解決、公開HTML取得、recent form正規化、lite分析、当日trend、欠損許容bundle化。
- 変更してよい範囲: 新規JRA予想材料モジュール、models/app/tests/fixtures/docsの関連箇所。
- 変更してはいけない範囲: 既存JRA/南関/netkeiba API契約、予想理論、analysis.sqliteスキーマ、無関係なリファクタ。

## 2. 実装前の読み順

1. 本書
2. `020-jra-prediction-materials-api実装計画書.md`
3. `010-jra-prediction-materials-api実装仕様書.md`
4. `005-jra-prediction-materials-api現行仕様整理.md`
5. `progress/006-次回着手メモ.md`
6. `src/jra_srb/nankan_prediction_service.py`
7. `src/jra_srb/service.py`
8. `src/jra_srb/netkeiba_provider.py`
9. `src/jra_srb/app.py`のJRA route部分
10. `tests/test_api.py`のJRA/南関bundle代表テスト

## 3. 実装順序

1. 3sourceの匿名公開fixtureを各1件だけ採取し、取得可能項目を固定する。
2. source key resolverとモデルを追加する。
3. recent formからlite値を算出する純粋関数とテストを追加する。
4. Provider/Extractorとfixtureテストを追加する。
5. JRA trend-contextを追加する。
6. public analysisを共有するJraPredictionServiceを追加する。
7. 個別routeとprediction-bundle routeを追加する。
8. API/利用ガイドを更新する。
9. 対象テスト、全体回帰、live 1件確認を実施し、progressへ結果を記録する。

## 4. 追加・修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 追加 | `src/jra_srb/jra_public_analysis_provider.py` | 3sourceの匿名GET、rate、retry、timeout |
| 追加 | `src/jra_srb/jra_public_analysis_extractors.py` | source別HTML抽出 |
| 追加 | `src/jra_srb/jra_prediction_materials.py` | source key、正規化、lite純粋計算 |
| 追加 | `src/jra_srb/jra_prediction_service.py` | trend、component共有、bundle |
| 修正 | `src/jra_srb/models.py` | JRA専用model。南関modelを流用しない |
| 修正 | `src/jra_srb/app.py` | dependencyと7 route |
| 追加 | `tests/test_jra_public_analysis_extractors.py` | 3source fixtureテスト |
| 追加 | `tests/test_jra_prediction_materials.py` | 純粋計算テスト |
| 追加 | `tests/test_jra_prediction_service.py` | 共有・partial・時点制御テスト |
| 修正 | `tests/test_api.py` | route/OpenAPI/validationテスト |
| 修正 | `docs/jra/05_API仕様.md` | 正本API契約 |
| 修正 | `docs/jra/04_利用ガイド.md` | 利用例と注意事項 |

## 5. 実装ルール

- 既存のProvider/Extractor/Service/FastAPI/Pydantic分離を踏襲する。
- 第三者ソース値でJRA公式値を上書きしない。
- public analysisはbundle内で1回だけ取得し、lite計算で共有する。
- 1source 1race 1GETを上限とし、馬ページ巡回を追加しない。
- `refresh=true`でもmin intervalを守る。
- source失敗をbundle全体の500へ昇格させない。
- `scope=visible_recent_races`、sample size、source、reasonを必ず返す。
- 対象レース以後の結果をtrendへ入れない。
- extractorに計算ロジックを入れず、HTML抽出と純粋計算を分離する。
- 実コードで確認できないHTML項目を、推測selectorで実装しない。

## 6. タスク詳細

| 順序 | タスク名 | 内容 | 入力 | 出力 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | 公開範囲監査 | 各URLを匿名で1回取得し公開/非公開を分類 | 指定3URL | fixture/項目表 | ログイン情報なしで再現可能 |
| 2 | race key | 3sourceのcodeを生成 | date/course/meeting/day/race | key model | サンプル一致 |
| 3 | models | status/recent/lite/bundleを追加 | 010 | Pydantic model | 欠損を表現可能 |
| 4 | materials | best/closing/styleを純粋計算 | recent form | lite models | 境界テスト成功 |
| 5 | provider | rate制御付き取得 | source key | HTML | 1GET制約成功 |
| 6 | extractor | 公開値を正規化 | fixture | public analysis | 有料値を含まない |
| 7 | trend | 過去確定Rのみ集計 | JraService | trend context | 未来リークなし |
| 8 | bundle | componentを共有・並列化 | 各service | bundle | partial response成功 |
| 9 | API/docs | routeと文書 | bundle | HTTP API | OpenAPI掲載 |
| 10 | 検証 | fixture/回帰/live 1件 | tests | 検証ログ | DoDを満たす |

## 7. テスト・検証引き継ぎ

Windows/uv方針に従い、実装担当は対象テスト後に全体を実行する。

```powershell
rtk uv run pytest -q tests/test_jra_public_analysis_extractors.py tests/test_jra_prediction_materials.py tests/test_jra_prediction_service.py
rtk uv run pytest -q tests/test_api.py
rtk uv run pytest -q
```

live確認はテスト成功後、対象レース1件だけで行い、アクセス数・source status・抽出値を記録する。

## 8. レビュー観点

- JRA公式値が補助sourceで上書きされていないか。
- `meeting_no/day`からのsource keyが正しいか。
- 1source 1GET、TTL、min intervalがテスト可能か。
- optional source失敗時に200 partialとなるか。
- lite値にscope/sample/sourceが付くか。
- 対象レース結果または未来レース結果のリークがないか。
- fixtureにCookie、トークン、不要な記事本文が残っていないか。
- 既存APIとDBスキーマを変更していないか。

## 9. 禁止事項

- ログイン、会員Cookie、課金情報を実装へ持ち込む。
- CAPTCHA・通信制限・robots制御を回避する。
- 馬ごとの追加ページを自動巡回する。
- 全開催バックフィルを同じ変更へ含める。
- 第三者の文章・画像・予想を保存またはAPIで再配布する。
- `lite`を全履歴・補正済み指数として返す。
- 既存の未コミット変更を上書き・整形・巻き戻しする。
- 仕様外の横断リファクタを行う。

## 10. 停止条件

- 匿名公開HTMLから対象値が取得できない。
- source keyが実ページと一致せず、一覧ページの追加巡回が必要になる。
- 利用条件上、機械取得の可否について新たな問題が判明する。
- 既存の未コミット変更と対象箇所が競合し、安全に統合できない。

停止時は推測で進めず、該当sourceを`disabled`にする案と影響範囲をユーザーへ提示する。

