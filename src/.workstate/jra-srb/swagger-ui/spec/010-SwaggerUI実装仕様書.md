# 010-SwaggerUI実装仕様書

## 0. 最初に読む要約

- 対象機能: Swagger UI 公開保証
- 改修目的: 既に動作する Swagger UI の URL 契約をコードとテストで明示する。
- 現行仕様の要点: FastAPI 標準の `/docs` と `/openapi.json` が既に有効。
- 実装時の最重要注意点: カスタム OpenAPI による既存エラースキーマと API メタデータを維持する。

## 1. 変更後仕様

- 入力: `GET /docs`, `GET /openapi.json`。
- 出力:
  - `GET /docs` は HTTP 200、`text/html` を返し、Swagger UI 初期化コードと `/openapi.json` の参照を含む。
  - `GET /openapi.json` は HTTP 200 の OpenAPI JSON を返す。
- 正常系: ブラウザで `/docs` を開くと API 一覧を参照でき、FastAPI 標準の Try it out を利用できる。
- 異常系: API サーバー停止時や CDN 到達不能時のブラウザ表示失敗は本変更で独自処理しない。
- 副作用: なし。

## 2. 既存構成における担当

- 入口: `jra_srb/app.py` の `FastAPI(...)`。
- スキーマ生成: `jra_srb/app.py` の `custom_openapi()`。
- 応答: FastAPI 標準のドキュメントルート。
- テスト: `../tests/test_api.py` の `TestClient(app)` パターンを流用する。

## 3. 実装配置

- 追加ファイル: なし。
- 修正ファイル候補:
  - `jra_srb/app.py`: `docs_url="/docs"` と `openapi_url="/openapi.json"` を明示する。
  - `../tests/test_api.py`: Swagger UI 公開契約の回帰テストを追加する。
- 既存流用: FastAPI、既存 `app`、既存 `custom_openapi()`、既存 `TestClient`。
- 新規抽象化: なし。単一設定と単一テストのため不要。

## 4. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| FastAPI 標準 UI を使う | `../pyproject.toml` | dependencies | FastAPI は既存依存 |
| API メタデータを維持する | `jra_srb/app.py` | 89-108 | title/version/description/tags が定義済み |
| カスタムスキーマを維持する | `jra_srb/app.py` | 1628-1646 | エラースキーマ追加とキャッシュが存在 |
| URL を維持する | `../README.md` | 71-72 | `/docs`, `/openapi.json` を利用者向けに公開済み |
| 回帰テストを追加する | `../tests/test_api.py` | 747 付近 | JSON は検証済みだが UI HTML は未検証 |

## 5. エラー・ログ・設定

- エラー処理: FastAPI 標準動作を維持し、独自例外処理は追加しない。
- ログ: 追加しない。
- 設定: URL は `FastAPI(...)` の引数として明示する。環境変数化はしない。
- 機密情報: OpenAPI に機密値や実トークンを追加しない。

## 6. Reference との差分

| Reference 仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| 対象 reference なし | FastAPI とカスタム OpenAPI が実装済み | 実コード優先 |

## 7. テスト観点

- 自動テスト:
  - `/docs` が 200 を返す。
  - Content-Type が `text/html` で始まる。
  - HTML に Swagger UI 初期化識別子と `/openapi.json` が含まれる。
  - 既存 `/openapi.json` テストが引き続き成功する。
- 手動確認:
  - サーバー起動後、`http://127.0.0.1:8000/docs` をブラウザで開く。
  - API のタグ、概要、パラメータが表示される。
  - `/health` など副作用のない API で Try it out を確認する。
- 回帰確認: `/mcp` と業務 API のルーティングを変更していないことを静的確認する。

## 8. 対象外

- Swagger UI アセットの自己ホスト、テーマ変更、日本語 UI 化。
- `/docs` の認証・認可、環境別無効化。
- ReDoc の追加変更。
- OpenAPI 定義全体の品質改善、タグメタデータの再設計。
- API 本体の機能変更。

## 9. 要確認事項

- 本番公開時に `/docs` と `/openapi.json` を外部公開してよいかは、別途運用判断が必要。
- オフライン表示が必要な場合は、静的アセット自己ホストを別仕様として起票する。
