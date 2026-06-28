# jra-srb

JRA のレース情報を取得するための Python SDK 兼ローカル HTTP API です。開催一覧、出馬表、オッズ、結果・払戻を取得し、FastAPI 経由で JSON API として扱えます。

> [!NOTE]
> このリポジトリは JRA 公式サイトの HTML を取得・解析するための実装を含みます。利用時は対象サイトの利用規約、アクセス頻度、運用上の制約を確認してください。

## 目次

- [主な機能](#主な機能)
- [必要環境](#必要環境)
- [セットアップ](#セットアップ)
- [API サーバーの起動](#api-サーバーの起動)
- [代表的な API](#代表的な-api)
- [レスポンスで扱う主なデータ](#レスポンスで扱う主なデータ)
- [Tiny HITL デモアプリ](#tiny-hitl-デモアプリ)
- [開発・テスト](#開発テスト)
- [プロジェクト構成](#プロジェクト構成)
- [実装メモ](#実装メモ)

## 主な機能

- JRA レース情報の取得 API
  - 開催一覧
  - 出馬表
  - オッズ
  - 結果・払戻
- FastAPI によるローカル HTTP API
- Swagger UI / OpenAPI による API 確認
- `fastapi-mcp` による MCP HTTP エンドポイント
- HTML 解析ルールを JSON 設定として管理
- 短時間のインメモリキャッシュ
- SQLite 永続キャッシュ
- fixture を使ったテストしやすい provider 抽象
- 日本語入力の正規化 API
- 保存済み結果の JSONL / SQLite 読み出し API
- レース検索 API
- 過去結果を JSONL / SQLite に保存する CLI / バッチ収集部品
- API から開始・確認できる結果収集 Job API
- upstream への同時実行数制限と最小アクセス間隔設定

## 必要環境

| 項目 | バージョン・内容 |
| --- | --- |
| Python | 3.12 以上 |
| パッケージ管理 | `uv` 推奨 |
| Web framework | FastAPI |
| テスト | pytest / pytest-asyncio |

## セットアップ

```bash
uv venv
uv pip install -e .[dev]
```

開発用依存を含めてインストールするため、テスト実行やローカル開発もこの手順で開始できます。

## API サーバーの起動

```bash
uv run uvicorn jra_srb.app:app --reload
```

起動後、次の URL から確認できます。

| 用途 | URL |
| --- | --- |
| API | `http://127.0.0.1:8000` |
| Swagger UI | `http://127.0.0.1:8000/docs` |
| OpenAPI JSON | `http://127.0.0.1:8000/openapi.json` |
| MCP HTTP endpoint | `http://127.0.0.1:8000/mcp` |

ヘルスチェック:

```bash
curl http://127.0.0.1:8000/health
```

期待されるレスポンス:

```json
{
  "status": "ok"
}
```

## 代表的な API

### 開催一覧

```http
GET /meetings/{date}/{course}
```

例:

```http
GET /meetings/2026-03-22/nakayama
```

指定した開催日・開催場の 1R から 12R までの一覧を取得します。

### 出馬表

開催日・開催場・レース番号で取得:

```http
GET /meetings/{date}/{course}/races/{race_no}/card
```

例:

```http
GET /meetings/2026-03-22/nakayama/races/11/card
```

`race_id` で取得:

```http
GET /races/{race_id}/card
```

例:

```http
GET /races/202603220611/card
```

### オッズ

開催日・開催場・レース番号で取得:

```http
GET /meetings/{date}/{course}/races/{race_no}/odds?bet_type={bet_type}
```

例:

```http
GET /meetings/2026-03-22/nakayama/races/11/odds?bet_type=trifecta&combination=1,2,3
```

`race_id` で取得:

```http
GET /races/{race_id}/odds?bet_type={bet_type}
GET /races/{race_id}/odds?bet_types=win,trifecta
```

例:

```http
GET /races/202603220611/odds?bet_type=quinella&combination=10,11
GET /races/202603220611/odds?bet_types=win,trifecta
```

対応している主な `bet_type`:

| bet_type | 内容 |
| --- | --- |
| `win` | 単勝・複勝系 |
| `quinella` | 馬連 |
| `wide` | ワイド |
| `exacta` | 馬単 |
| `trio` | 3連複 |
| `trifecta` | 3連単 |

`combination` はカンマ区切りで指定します。

```http
combination=4,10
combination=4,10,11
```

キャッシュを使わず再取得したい場合は `refresh=true` を付けます。

```http
GET /meetings/2026-03-22/nakayama/races/11/odds?bet_type=wide&combination=4,10&refresh=true
```

### 結果・払戻

開催日・開催場・レース番号で取得:

```http
GET /meetings/{date}/{course}/races/{race_no}/result
```

例:

```http
GET /meetings/2026-03-22/nakayama/races/11/result
```

`race_id` で取得:

```http
GET /races/{race_id}/result
```

例:

```http
GET /races/202603220611/result
```

### 互換・fixture 向け API

```http
GET /races?date=YYYY-MM-DD&course=optional
```

例:

```http
GET /races?date=2026-03-22&course=nakayama
```

### 入力正規化

日本語の開催場名、レース表記、券種名を API 用コードに変換できます。

```http
GET /normalize?course=中山&race=11R&bet_type=3連単&combination=1,2,3
```

レスポンス例:

```json
{
  "course": "nakayama",
  "race_no": 11,
  "bet_type": "trifecta",
  "combination": ["1", "2", "3"]
}
```

### 保存済み結果

JSONL または SQLite に保存済みのレース結果を取得できます。

```http
GET /stored/results/{race_id}
GET /stored/results?from_date=2026-03-22&to_date=2026-03-22&course=nakayama&limit=100&offset=0
```

一覧 API はページング形式で返します。

```json
{
  "items": [],
  "total": 0,
  "limit": 100,
  "offset": 0
}
```

### レース検索

開催日、開催場、キーワードから `race_id` を探せます。`race_id` が分からない状態で、出馬表・オッズ・結果 API へ進むための入口です。

```http
GET /search/races?date=2026-03-22&course=nakayama&keyword=11R
```

レスポンス例:

```json
{
  "items": [
    {
      "race_id": "202603220611",
      "date": "2026-03-22",
      "course": "nakayama",
      "race_no": 11,
      "race_name": "Chiba Stakes",
      "start_time": "15:45"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

### 結果収集 Job API

過去結果の収集を HTTP request 内で完了まで待たず、job として開始できます。保存先は `jsonl` または `sqlite` を指定できます。

```bash
curl -X POST http://127.0.0.1:8000/jobs/result-collections \
  -H "content-type: application/json" \
  -d '{
    "from_date": "2026-03-22",
    "to_date": "2026-03-22",
    "courses": ["nakayama"],
    "storage": "jsonl",
    "output": "data/results.jsonl",
    "retries": 1
  }'
```

作成直後のレスポンス:

```json
{
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

状態確認:

```http
GET /jobs/result-collections/{job_id}
GET /jobs/result-collections
```

job の状態は `queued`, `running`, `succeeded`, `failed` のいずれかです。失敗時は `error` に理由が入ります。job の記録はプロセス内メモリに保持されるため、API サーバーを再起動すると消えます。

### エラーレスポンス

API エラーは次の形式で返します。`request_id` はレスポンスヘッダー `x-request-id` にも入ります。

```json
{
  "error": {
    "code": "bad_request",
    "message": "unsupported bet_type=foobar",
    "request_id": "..."
  }
}
```

## レスポンスで扱う主なデータ

| モデル | 内容 |
| --- | --- |
| `RaceSummary` | レース ID、レース番号、レース名、開催場、発走時刻 |
| `MeetingSnapshot` | 開催日・開催場ごとのレース一覧 |
| `RaceCard` | レース情報、距離、芝・ダート、出走馬一覧 |
| `RaceOdds` | 券種、組み合わせ、オッズ、人気 |
| `RaceResult` | 着順、馬番、馬名、騎手、タイム、払戻 |

各レスポンスには取得元を示す `source`、取得時刻の `fetched_at`、キャッシュ利用有無の `cache_hit` が含まれます。

## Tiny HITL デモアプリ

Human in the Loop の流れを確認するための最小 Web アプリも含まれています。

```bash
uv run uvicorn hitl_tiny_counter.app:app --reload --port 8010
```

起動後、次の URL を開きます。

```text
http://127.0.0.1:8010
```

## 開発・テスト

テスト実行:

```bash
uv run --extra dev pytest -q
```

Windows PowerShell で `.venv-win` を使う場合:

```powershell
$env:UV_PROJECT_ENVIRONMENT='.venv-win'
uv run --extra dev pytest -q
```

WSL / Linux では通常の `.venv` を使います。

```bash
uv run --extra dev pytest -q
```

## CLI

過去結果を保存先へ収集できます。

```bash
uv run jra-srb collect-results --from-date 2026-03-22 --to-date 2026-03-22 --courses nakayama --output data/results.jsonl
```

SQLite に保存する場合:

```bash
uv run jra-srb collect-results --from-date 2026-03-22 --to-date 2026-03-22 --courses nakayama --storage sqlite --output data/results.sqlite
```

## 環境変数

| 変数 | 内容 |
| --- | --- |
| `JRA_SRB_RESULTS_STORAGE` | 保存済み結果 API の backend。`jsonl` または `sqlite`。既定値は `jsonl` |
| `JRA_SRB_RESULTS_PATH` | 保存済み結果 API が読む JSONL パス。既定値は `data/results.jsonl` |
| `JRA_SRB_CACHE_PATH` | 指定時に SQLite 永続 cache を使う |
| `JRA_SRB_UPSTREAM_MAX_CONCURRENCY` | JRA upstream への最大同時 request 数。既定値は `5` |
| `JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS` | JRA upstream への request 開始間隔の最小秒数。既定値は `0` |
| `UV_PROJECT_ENVIRONMENT` | Windows では `.venv-win` を指定すると `uv run` で Windows 用仮想環境を使える |

このプロジェクトでは `tests/fixtures` 配下の HTML fixture を使い、実サイトへアクセスしなくても主要な解析・API 挙動を検証できるようにしています。

## プロジェクト構成

```text
.
|-- docs/                         # 設計資料・利用ガイド
|-- src/
|   |-- hitl_tiny_counter/        # HITL 確認用の最小デモアプリ
|   `-- jra_srb/
|       |-- app.py                # FastAPI アプリケーション
|       |-- batch.py              # 過去結果収集用のバッチ部品
|       |-- cache.py              # TTL キャッシュ
|       |-- cli.py                # 結果収集 CLI
|       |-- extractors.py         # HTML 解析処理
|       |-- jobs.py               # 結果収集 Job API の in-memory registry
|       |-- models.py             # Pydantic モデル
|       |-- navigation.py         # JRA ページ遷移情報の解決
|       |-- normalization.py      # 日本語入力と API コードの正規化
|       |-- provider.py           # HTTP / fixture provider
|       |-- service.py            # API 用のユースケース層
|       `-- config/parsers/       # HTML 解析ルール
|-- tests/                        # API・service・provider・batch のテスト
|-- pyproject.toml
`-- README.md
```

## 実装メモ

- デフォルトの provider は `HttpProvider` です。
- テストでは `FixtureProvider` を使い、HTML fixture から deterministic にレスポンスを生成します。
- HTML 解析は `src/jra_srb/config/parsers/*.json` と `extractors.py` を中心に構成されています。
- API 層は `app.py`、ユースケース層は `service.py` に分離されています。
- オッズ取得は短い TTL でキャッシュされます。`refresh=true` を指定するとキャッシュを避けて再取得します。
- 過去結果のバッチ収集では `JsonlRaceResultStorage` を使い、1 レース 1 行の JSONL として保存できます。

## 関連ドキュメント

- [JRA プロジェクト概要](docs/jra/01_プロジェクト概要.md)
- [アーキテクチャ](docs/jra/02_アーキテクチャ.md)
- [利用ガイド](docs/jra/04_利用ガイド.md)
- [API 仕様](docs/jra/05_API仕様.md)
- [スクレイピングと運用注意](docs/jra/06_スクレイピングと運用注意.md)
