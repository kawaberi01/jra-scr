# 020-SwaggerUI実装計画書

## 1. 対象と目的

- 対象機能: Swagger UI 公開保証
- 改修目的: `/docs` と `/openapi.json` の既存公開契約を明示し、回帰を検知できるようにする。
- 今回の対象範囲: FastAPI 初期化設定、API テスト。
- 今回やらないこと: 新規パッケージ、認証、自己ホスト、API 本体変更、横断リファクタ。

## 2. 実装フェーズ

### Phase 1: 事前確認

- 実装開始時の差分を確認し、`jra_srb/app.py` と `../tests/test_api.py` のユーザー変更を保全する。

### Phase 2: URL 契約の明示

- `FastAPI(...)` に `docs_url` と `openapi_url` を追加する。

### Phase 3: 回帰テスト

- 既存 `TestClient(app)` の形式で `/docs` の契約テストを追加する。

### Phase 4: 静的レビュー

- `custom_openapi()`、MCP マウント、業務 API へ意図しない変更がないことを差分で確認する。

### Phase 5: テスト引き継ぎ

- 対象テストと、必要に応じた全テストを人間または実装フェーズで実行する。

## 3. タスク一覧

| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| SUI-01 | 1 | 対象ファイルの既存差分確認 | git status/diff | 競合有無 | なし | ユーザー変更を識別済み |
| SUI-02 | 2 | `/docs` と `/openapi.json` を明示設定 | `app.py` | FastAPI 設定差分 | SUI-01 | 既存 URL と挙動を維持 |
| SUI-03 | 3 | Swagger UI 契約テスト追加 | `test_api.py` | 新規テスト | SUI-02 | status/content-type/schema URL を検証 |
| SUI-04 | 4 | 限定差分レビュー | git diff | レビュー結果 | SUI-03 | 対象外変更なし |
| SUI-05 | 5 | テスト実行引き継ぎ | 実装差分 | 検証記録 | SUI-04 | コマンドと結果を記録 |

## 4. 完了判定

- 実装完了条件: URL が明示され、Swagger UI 契約テストが追加されている。
- テスト完了条件: Swagger/OpenAPI 対象テストが成功し、既存テストに新規失敗がない。
- レビュー完了条件: 追加依存なし、API 本体・カスタム OpenAPI・MCP に意図しない変更なし。

## 5. 別タスク候補

- 本番環境でのドキュメント公開制御。
- Swagger UI 静的アセットの自己ホストによるオフライン対応。
- OpenAPI タグ説明を含むメタデータ完全性の追加検証。
