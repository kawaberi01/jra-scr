# API 品質追加改修 実装計画書

## P0: Storage backend 設定統一

### 目的

API と CLI で保存先選択の考え方を揃える。

### 現状

- CLI は `--storage jsonl|sqlite` を選べる。
- API は `JRA_SRB_RESULTS_PATH` を読むが、backend は JSONL 固定。

### 実装タスク

- `JRA_SRB_RESULTS_STORAGE=jsonl|sqlite` を追加する。
- `get_result_storage()` で `JRA_SRB_RESULTS_STORAGE` と `JRA_SRB_RESULTS_PATH` を見て storage を構築する。
- 不正な storage 値は起動時または request 時に `bad_request` で返す。
- README / docs に環境変数を追記する。
- API test を追加する。

### 完了条件

- `JRA_SRB_RESULTS_STORAGE=sqlite` で API が SQLite 保存済み結果を読める。
- CLI と API の storage 選択が同じ用語になる。

## P0: Upstream アクセス制御

### 目的

JRA upstream への過剰アクセスや同時アクセスを抑える。

### 現状

- retry / backoff はある。
- 同時実行数制限、最小アクセス間隔はない。

### 実装タスク

- `HttpProvider` に async semaphore を追加する。
- `JRA_SRB_UPSTREAM_MAX_CONCURRENCY` を service / app build 時に渡せるようにする。
- `JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS` を追加する。
- request 前に最小間隔を守る throttle を入れる。
- provider test を追加する。

### 完了条件

- 設定値で upstream 同時実行数を制限できる。
- 設定値で request 間隔を空けられる。
- 既存 retry / backoff と競合しない。

## P1: 結果収集 Job API

### 目的

長時間の過去結果収集を HTTP request に閉じ込めず、job として扱えるようにする。

### 現状

- CLI で収集はできる。
- API から開始・状態確認はできない。

### 実装タスク

- `POST /jobs/result-collections` を追加する。
- request model:
  - `from_date`
  - `to_date`
  - `courses`
  - `storage`
  - `output`
  - `retries`
- `GET /jobs/result-collections/{job_id}` を追加する。
- 最初は in-memory registry でよい。
- 状態は `queued`, `running`, `succeeded`, `failed`。
- エラー時は message を保存する。
- tests では fake service / storage を使う。

### 完了条件

- API から収集開始できる。
- job_id で状態確認できる。
- 失敗時の状態と message が返る。

## P1: Observability 強化

### 目的

障害時に API response と log を突合しやすくする。

### 現状

- `x-request-id` はある。
- request log に request_id は入る。
- service / provider log に request_id は入っていない。
- JSON log 出力設定はない。

### 実装タスク

- `contextvars` で request_id を保持する。
- service / provider log の extra に request_id を付ける。
- `JRA_SRB_LOG_FORMAT=json|text` を追加する。
- JSON formatter を標準 logging で実装する。

### 完了条件

- request, service, provider のログに同じ request_id が出る。
- JSON log 出力を選べる。

## P2: API key guard / CORS 設定

### 目的

ローカル専用から外部公開へ移る場合の境界を用意する。

### 現状

- 認証なし。
- CORS 設定なし。

### 実装タスク

- `JRA_SRB_API_KEY` が設定されている場合だけ API key を要求する。
- `x-api-key` header を見る。
- `/health` は API key 対象外にするか方針を決める。
- `JRA_SRB_CORS_ORIGINS` を追加する。
- 未設定時は CORS middleware を追加しない。

### 完了条件

- API key 設定時に未認証 request が 401 になる。
- CORS は明示設定時だけ有効になる。

## P2: Public response DTO 安定化

### 目的

内部 model 変更が API 契約へ直接漏れるのを避ける。

### 現状

- `RaceCard`, `RaceOdds`, `RaceResult` など内部 model をほぼそのまま返している。
- `source`, `cache_hit`, `fetched_at` が常に返る。

### 実装タスク

- public response model を定義する。
- `include_meta=true` の場合だけ `source`, `cache_hit`, `fetched_at` を含める。
- まず保存済み結果 API ではなく live API から段階導入する。

### 完了条件

- OpenAPI response model が public DTO を示す。
- 既存レスポンス互換を壊す場合は versioning 方針を決めてから実装する。

## 推奨実装順

1. Storage backend 設定統一
2. Upstream アクセス制御
3. Observability 強化
4. 結果収集 Job API
5. API key guard / CORS 設定
6. Public response DTO 安定化

## 次回実装の推奨単位

最初は P0 の 2 件をまとめる。

- Storage backend 設定統一
- Upstream アクセス制御

理由:

- どちらも運用事故を減らす改修。
- 既存 API 契約への破壊的変更が少ない。
- テストで環境変数と provider 挙動を固定しやすい。
