# API仕様

## ヘルスチェック

### `GET /health`

API プロセスの生存確認です。外部通信は行いません。

### `GET /health/upstream`

JRA upstream への軽量な到達性を確認します。

## 入力正規化

### `GET /normalize`

日本語の開催場名、レース表記、券種名を API 用コードへ変換します。

クエリ:

- `course`: 例 `中山`, `nakayama`
- `race`: 例 `11R`, `第11レース`
- `bet_type`: 例 `3連単`, `trifecta`
- `combination`: 例 `1,2,3`

## 開催・出馬表・オッズ・結果

### `GET /races?date=YYYY-MM-DD&course=optional`

race summary 一覧を取得します。

### `GET /meetings/{date}/{course}`

開催日と開催場から 1R から 12R の一覧を取得します。

### `GET /meetings/{date}/{course}/races/{race_no}/card`

開催日、開催場、レース番号から出馬表を取得します。

### `GET /meetings/{date}/{course}/races/{race_no}/odds`

開催日、開催場、レース番号からオッズを取得します。

クエリ:

- `bet_type`: `win`, `quinella`, `wide`, `exacta`, `trio`, `trifecta`
- `combination`: 任意。例 `1,2,3`
- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /meetings/{date}/{course}/races/{race_no}/result`

開催日、開催場、レース番号から結果と払戻を取得します。

### `GET /races/{race_id}/card`

`race_id` で出馬表を取得します。

### `GET /races/{race_id}/odds`

`race_id` でオッズを取得します。

クエリ:

- `bet_type`: 単一券種
- `bet_types`: 複数券種。例 `win,trifecta`
- `combination`: 任意
- `refresh`: 任意

### `GET /races/{race_id}/result`

`race_id` で結果と払戻を取得します。

## 保存済み結果

### `GET /stored/results/{race_id}`

保存済み結果を `race_id` で取得します。

### `GET /stored/results`

保存済み結果を検索します。

クエリ:

- `from_date`: 任意。検索開始日
- `to_date`: 任意。検索終了日
- `course`: 任意。開催場
- `limit`: 返却件数。1 から 500
- `offset`: スキップ件数。0 以上

レスポンス:

```json
{
  "items": [],
  "total": 0,
  "limit": 100,
  "offset": 0
}
```

## レース検索

### `GET /search/races`

開催日、開催場、キーワードから race_id を探します。保存済み結果は読まず、既存のレース一覧取得 API を検索・ページングします。

クエリ:

- `date`: 必須。開催日。例 `2026-03-22`
- `course`: 任意。開催場コード。例 `nakayama`
- `keyword`: 任意。`race_id`、レース名、開催場、レース番号の部分一致
- `limit`: 返却件数。1 から 100
- `offset`: スキップ件数。0 以上

レスポンス:

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

## 結果収集 Job API

### `POST /jobs/result-collections`

過去結果の収集を非同期 job として開始します。収集には既存の `PastResultCollector` を使い、保存先は JSONL または SQLite です。

Request body:

```json
{
  "from_date": "2026-03-22",
  "to_date": "2026-03-22",
  "courses": ["nakayama"],
  "storage": "jsonl",
  "output": "data/results.jsonl",
  "retries": 1
}
```

- `from_date`: 必須。収集開始日
- `to_date`: 必須。収集終了日
- `courses`: 必須。1 件以上の開催場コード
- `storage`: 任意。`jsonl` または `sqlite`
- `output`: 任意。保存先パス
- `retries`: 任意。0 以上

レスポンスは `202 Accepted` です。

```json
{
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

### `GET /jobs/result-collections`

現在の API プロセスが保持している job 一覧を返します。

```json
{
  "items": [],
  "total": 0
}
```

### `GET /jobs/result-collections/{job_id}`

job の状態を返します。

```json
{
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "succeeded",
  "from_date": "2026-03-22",
  "to_date": "2026-03-22",
  "courses": ["nakayama"],
  "storage": "jsonl",
  "output": "data/results.jsonl",
  "retries": 1,
  "created_at": "2026-03-22T00:00:00Z",
  "started_at": "2026-03-22T00:00:01Z",
  "finished_at": "2026-03-22T00:00:05Z",
  "message": "collection succeeded",
  "error": null
}
```

job status:

- `queued`
- `running`
- `succeeded`
- `failed`

job の記録は in-memory です。API サーバーを再起動すると job 一覧と状態は消えます。

## エラーレスポンス

API エラーは次の形式で返します。

```json
{
  "error": {
    "code": "bad_request",
    "message": "unsupported bet_type=foobar",
    "request_id": "..."
  }
}
```

`request_id` はレスポンスヘッダー `x-request-id` にも入ります。

## 環境変数

| 変数 | 内容 |
| --- | --- |
| `JRA_SRB_RESULTS_STORAGE` | 保存済み結果 API の backend。`jsonl` または `sqlite`。既定値は `jsonl` |
| `JRA_SRB_RESULTS_PATH` | 保存済み結果 API が読む JSONL パス。既定値は `data/results.jsonl` |
| `JRA_SRB_CACHE_PATH` | 指定時に SQLite 永続 cache を使う |
| `JRA_SRB_UPSTREAM_MAX_CONCURRENCY` | JRA upstream への最大同時 request 数。既定値は `5` |
| `JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS` | JRA upstream への request 開始間隔の最小秒数。既定値は `0` |
