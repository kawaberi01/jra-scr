# 030-SwaggerUI実装指示書

## 1. 対象概要

- 対象機能: Swagger UI 公開保証
- 改修目的: FastAPI 標準 Swagger UI の既存公開状態をコードとテストで固定する。
- この機能が行う処理: `/docs` で Swagger UI HTML、`/openapi.json` で OpenAPI スキーマを返す。
- 変更してよい範囲: `jra_srb/app.py` の `FastAPI(...)` 引数、`../tests/test_api.py` の関連テスト。
- 変更してはいけない範囲: API 業務処理、モデル、DB、外部通信、MCP、カスタムエラーレスポンス、依存関係。

## 2. 実装順序

1. `rtk git status --short` と対象ファイル限定の差分を確認し、既存変更との競合を判断する。
2. `FastAPI(...)` に `docs_url="/docs"` と `openapi_url="/openapi.json"` を明示する。
3. `../tests/test_api.py` に `/docs` の契約テストを追加する。
4. 対象ファイルだけを差分確認する。
5. 人間または許可された実装フェーズへテスト実行を引き継ぐ。

## 3. 追加・修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 修正 | `jra_srb/app.py` | Swagger UI と OpenAPI JSON の URL を明示 |
| 修正 | `../tests/test_api.py` | `/docs` の status、HTML、OpenAPI URL を検証 |

## 4. 実装ルール

- 新規依存を追加しない。FastAPI 標準 Swagger UI を使う。
- `custom_openapi()` と `app.openapi = custom_openapi` を維持する。
- 既存の title、version、description、openapi_tags を変更しない。
- 既存構成にない DTO、Service、helper、設定クラスを追加しない。
- URL の環境変数化や条件付き公開を混ぜない。
- progress 更新はイベント駆動・最小更新とする。

## 5. タスク詳細

| 順序 | タスク名 | 内容 | 入力 | 出力 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | 競合確認 | `app.py`, `test_api.py` の既存差分確認 | git diff | 競合判断 | ユーザー変更を上書きしない |
| 2 | URL 明示 | `FastAPI(...)` 引数を追加 | 現行 app | 設定差分 | `/docs`, `/openapi.json` を指定 |
| 3 | UI テスト | `TestClient` で `/docs` を取得 | 既存テスト様式 | 回帰テスト | 200、HTML、SwaggerUIBundle、OpenAPI URL を検証 |
| 4 | 静的確認 | 限定差分を読む | 実装差分 | 確認記録 | 対象外変更なし |

## 6. テスト・検証引き継ぎ

- 対象テスト候補: `rtk uv run pytest -q tests/test_api.py -k "swagger_ui or openapi"`
- 全体テスト候補: `rtk uv run pytest -q`
- 手動確認候補:
  1. `uv run uvicorn jra_srb.app:app --reload`
  2. ブラウザで `http://127.0.0.1:8000/docs` を開く。
  3. `/health` を Try it out し、正常応答を確認する。
- 分析フェーズでは上記を実行しない。

## 7. レビュー観点

- `/docs` がカスタム OpenAPI の `/openapi.json` を参照しているか。
- `ApiError` と `ApiErrorResponse` のスキーマ追加が維持されているか。
- Swagger UI 以外のルート、MCP マウント、ミドルウェアに差分がないか。
- HTML 全文の厳密一致など、FastAPI 内部実装に過度に依存するテストになっていないか。
- 新規依存や生成物が増えていないか。

## 8. 禁止事項

- `Swashbuckle` など .NET 用パッケージを導入しない。
- Swagger UI の独自 HTML を再実装しない。
- CDN 自己ホスト、認証、テーマ変更を同時に実装しない。
- ユーザーの既存変更を上書き・整形しない。
- 分析指示だけの段階でビルド、テスト、アプリ起動を行わない。

## 9. 停止条件

- 対象行に未解決の既存変更があり、安全に統合できない場合。
- 本番公開制御、認証、オフライン対応が必須要件として追加された場合。
- FastAPI 標準 `/docs` を使わず別 UI を求める要件へ変わった場合。
