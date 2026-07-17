# 030-JRA予想評価参照API実装指示書

## 1. 対象概要

- 対象機能: JRA予想・評価参照API
- 改修目的: 保存済み予想・評価の詳細、一覧、集計をHTTP APIから取得可能にする。
- この機能が行う処理: `analysis.sqlite`の既存テーブルを読み、JSONと真偽値を型付きレスポンスへ復元する。
- 変更してよい範囲: `src/jra_srb/models.py`、`analysis_store.py`、`app.py`、`tests/test_analysis_store.py`、`tests/test_api.py`、`docs/jra/05_API仕様.md`、当Featureのprogress。
- 変更してはいけない範囲: DB schema、予想生成、評価計算、既存POST契約、MCP公開、他のCLI/API、運用データ。

## 2. 実装順序

1. `progress/006-次回着手メモ.md`、本書、`020`を読む。
2. 対象3ソースの既存差分を限定表示し、競合時は停止する。
3. `models.py`へ参照用modelを追加する。
4. `analysis_store.py`へ詳細、一覧、集計methodを追加する。
5. `app.py`へGET routeを追加する。`/summary`を動的ID routeより前に置く。
6. Store/APIテストを追加する。
7. API仕様書を更新し、静的自己レビューする。
8. progressを必要最小限更新し、テスト実行コマンドを人間へ引き継ぐ。

## 3. 追加・修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 修正 | `src/jra_srb/models.py` | `PredictionTicketRecord`、`PredictionRecord`、`PredictionRecordPage`、`EvaluationTicketResultRecord`、`EvaluationRecord`、`EvaluationRecordPage`、`EvaluationSummary`を追加。 |
| 修正 | `src/jra_srb/analysis_store.py` | `get/list_prediction_record(s)`、`get/list_evaluation_record(s)`、`summarize_evaluations`を追加。 |
| 修正 | `src/jra_srb/app.py` | 仕様書記載のGET route 5本を追加。 |
| 修正 | `tests/test_analysis_store.py` | JSON/bool/券復元、filter、pagination、404、summaryを追加。 |
| 修正 | `tests/test_api.py` | 各GET APIのHTTP契約を追加。 |
| 修正 | `docs/jra/05_API仕様.md` | route、query、主レスポンスを追加。 |

## 4. 実装ルール

- 既存構成にないRepository、Service、DI分離を新設しない。
- DB queryは`?` bind parameterを使い、query値をSQL文字列へ埋め込まない。
- 一覧はcountとpage取得を同じfilterで行う。
- detail methodが関連券を同一接続内で取得し、JSONをdecodeする。
- SQLite integerはPydanticへ渡す前に`bool()`変換し、nullableは`None`を保持する。
- 公開レスポンスでは`*_json`というDB列名を使わず、`pre_race_snapshot`、`prediction`、`evaluation`とする。
- `from_date > to_date`はrouteで`BadRequestError`にする。
- 既存の未コミット変更を上書き、整形、巻き戻ししない。

## 5. タスク詳細

| 順序 | タスク名 | 内容 | 入力 | 出力 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | Model追加 | 仕様書1章のresponse modelを定義 | 現行schema | 型定義 | OpenAPIで項目が確定可能 |
| 2 | 予想参照Store | 詳細と一覧を実装 | predictions系table | model/page | filterとpaginationが仕様一致 |
| 3 | 評価参照Store | 詳細、一覧、summaryを実装 | evaluations系table | model/page/summary | boolと集計式が仕様一致 |
| 4 | Route追加 | GET 5本、query、response_modelを追加 | Store method | HTTP API | 404/400/422契約が既存handlerと整合 |
| 5 | テスト追加 | Store/APIの正常・異常系 | 仕様7章 | pytest test | テストコードが対象契約を検証 |
| 6 | 文書・確認 | API仕様更新と静的レビュー | 全変更 | docs/progress | 対象外混入なし |

## 6. テスト・検証引き継ぎ

人間が実行する候補:

```powershell
rtk uv run pytest -q "tests\test_analysis_store.py" "tests\test_api.py"
```

必要なら全体回帰:

```powershell
rtk uv run pytest -q
```

静的確認観点:

- import名、model名、Store戻り値、response_modelの一致。
- `/jra/evaluations/summary`が`/{evaluation_id}`より前に登録されること。
- `total`と`items`に同じfilterが適用されること。
- JSON decodeとbool/null変換が全detail/listで一貫すること。
- 既存POST routeとMCP operation listが変更されていないこと。

## 7. レビュー観点

- 詳細APIが関連券を漏れなく返すか。
- 日付filterが`races`とのjoinにより意図どおり動くか。
- summaryの分母、0件、nullable指標が安全か。
- query injection、無制限取得、DBパス漏洩がないか。
- API仕様書と実routeが一致するか。

## 8. 禁止事項

- DB schema/indexの追加。
- 既存予想・評価データの更新や移行。
- 既存APIのresponse変更。
- `sqlite3`をAPI routeから直接呼ぶこと。
- 汎用SQL API、削除API、更新APIの追加。
- 対象外ファイルの整形やリファクタ。
- コミット、push、デプロイ。
- 実装skillの許可なしにビルド・テスト・外部APIを実行すること。

## 9. 停止条件

- 対象ファイルの既存差分と同じ箇所を安全に統合できない。
- 現行schemaが本仕様の確認時点から変わっている。
- DB schema変更なしでは要件を満たせないことが判明した。
- JRA以外の予想を同じrouteへ含めるかという新たな業務判断が必要になった。
- 既存POST契約の変更が必要になった。

