# 000-SwaggerUI前提メモ

## 0. 最初に読む要約

- 対象機能名: Swagger UI 公開保証
- 改修目的: OpenAPI 準拠の API 仕様をブラウザで確認・試行できる状態を、明示的な設定と回帰テストで保証する。
- 現行仕様の要点: FastAPI 標準機能により `/docs` と `/openapi.json` は既に有効で、README にも URL が記載されている。
- 実装時に最も注意すべき点: `app.openapi = custom_openapi` による既存の `ApiError` スキーマ追加を壊さない。
- reference_status: `not_found`（同梱 reference に jra-srb / FastAPI 向け資料なし）
- 実コード優先で採用した判断: Swagger UI 用の別パッケージは追加せず、既存 FastAPI の標準 UI を利用する。
- spec_root: `.workstate/jra-srb/swagger-ui/spec/`
- progress_root: `.workstate/jra-srb/swagger-ui/progress/`
- 実装 skill への主入力: `030-SwaggerUI実装指示書.md`, `020-SwaggerUI実装計画書.md`
- ビルド・テスト実行: 分析フェーズでは実行せず、人間または実装フェーズへ引き継ぐ。

## 1. 対象

- 対象 root: `D:\develop\jra-scr\src`
- 対象プロジェクト: `jra-srb`
- 対象機能: FastAPI が提供する Swagger UI と OpenAPI JSON
- 関連 API: `jra_srb.app:app` に登録された全 HTTP API

## 2. 入力情報

- ユーザー要件: 「Swagger UIをこのプロジェクトに適用したい。まず仕様をスキルで起こす」
- 参照した主要コード: `jra_srb/app.py`, `../pyproject.toml`, `../README.md`, `../tests/test_api.py`
- 外部一次資料:
  - [FastAPI First Steps](https://fastapi.tiangolo.com/tutorial/first-steps/)
  - [FastAPI Configure Swagger UI](https://fastapi.tiangolo.com/how-to/configure-swagger-ui/)
  - [FastAPI Extending OpenAPI](https://fastapi.tiangolo.com/how-to/extending-openapi/)

## 3. 作成する成果物

- `005-SwaggerUI現行仕様整理.md`
- `010-SwaggerUI実装仕様書.md`
- `020-SwaggerUI実装計画書.md`
- `030-SwaggerUI実装指示書.md`

## 4. 注意点

- FastAPI は既に依存関係に含まれ、Swagger UI は標準で `/docs` に公開されるため、新規ライブラリ導入は不要。
- 標準 Swagger UI の JavaScript/CSS は既定では CDN から読み込まれる。オフライン対応は今回の対象外。
- `/docs` と `/openapi.json` は API サーバーへ到達できる利用者に公開される。認証や環境別無効化は今回の対象外。
- ワークツリーには多数の既存変更があるため、本機能と無関係な変更には触れない。
