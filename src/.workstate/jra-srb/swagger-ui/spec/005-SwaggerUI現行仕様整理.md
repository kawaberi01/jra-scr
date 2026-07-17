# 005-SwaggerUI現行仕様整理

## 1. 現行構成

- `../pyproject.toml` は `fastapi>=0.115` と `uvicorn>=0.34` を依存関係として持つ。
- `jra_srb/app.py:89` で `FastAPI` アプリを生成している。
- `docs_url` と `openapi_url` は明示されていないため、FastAPI 標準値の `/docs` と `/openapi.json` が使われる。
- `jra_srb/app.py:1628` の `custom_openapi()` が OpenAPI スキーマを生成し、`ApiError` と `ApiErrorResponse` を追加してキャッシュする。
- `jra_srb/app.py:1646` で `app.openapi` を上記関数へ差し替えている。
- `../README.md:71` と `../README.md:72` に Swagger UI と OpenAPI JSON の URL が記載されている。

## 2. 現行の入力・出力

- 入力: ブラウザまたは HTTP クライアントからの `GET /docs`、`GET /openapi.json`。
- 出力:
  - `/docs`: Swagger UI を読み込む HTML。
  - `/openapi.json`: 登録済み API、入出力モデル、タグ、説明、エラーモデルを含む OpenAPI JSON。
- Swagger UI の Try it out は、表示中の API サーバーに対してリクエストを送る。

## 3. 副作用・設定・エラー

- DB 更新、ファイル更新、キュー送信は行わない。
- OpenAPI スキーマは初回生成後に `app.openapi_schema` へキャッシュされる。
- Swagger UI の静的アセット読み込みは FastAPI 標準の CDN URL に依存する。
- API 認証や Swagger UI 専用認証は現行コードから確認できない。

## 4. 既存テスト

- `../tests/test_api.py:747` 付近の `test_openapi_contains_japanese_api_guidance` が `/openapi.json` の 200 応答、タイトル、説明、主要パス、パラメータ説明、`ApiErrorResponse` を検証する。
- `/docs` の 200 応答、HTML、OpenAPI URL の埋め込みを直接検証するテストは確認できない。

## 5. 要件との差分

| 要件 | 現行 | 差分 |
| --- | --- | --- |
| ブラウザで API 仕様を確認できる | `/docs` が既に有効 | 機能差分なし |
| OpenAPI 仕様を参照できる | `/openapi.json` が既に有効 | 機能差分なし |
| 導入状態を保守可能にする | URL は暗黙の既定値、`/docs` のテストなし | 明示設定と回帰テストを追加する余地あり |

## 6. Reference との差分

- reference_status は `not_found`。実コードと FastAPI 公式資料を根拠に判断した。
- FastAPI 公式資料の標準 `/docs`、`/openapi.json` と現行 README の記載は一致する。

## 7. 未確認・対象外

- 実サーバーを起動したブラウザ目視は未実施。
- CDN を遮断した環境での表示可否は未確認かつ対象外。
- 本番環境での Swagger UI 公開可否、認証追加、ReDoc の扱いは対象外。
