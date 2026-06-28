# 010-additional-api-features 実装仕様書

## 0. 最初に読む要約

- 対象機能:
  - 結果収集 Job API
  - レース検索 API
- 改修目的:
  - CLI で可能な過去結果収集を API から非同期 job として開始・確認できるようにする。
  - 開催日・開催場・キーワードから、対象 race_id を API で探せるようにする。
- 現行仕様の要点:
  - `PastResultCollector` は date range と course list を受けて保存先へ結果を書ける。
  - API は `JRA_SRB_RESULTS_STORAGE=jsonl|sqlite` と `JRA_SRB_RESULTS_PATH` で保存済み結果を読める。
  - `JraService.get_races(date, course)` は開催日のレース概要を返せる。
  - API のエラー形式は `{"error":{"code","message","request_id"}}` に統一済み。
- 実装時の最重要注意点:
  - Job API は request を長時間ブロックしない。
  - registry はプロセス内メモリに閉じる。
  - 既存 parser / provider / storage の契約を変更しない。

## 1. 変更後仕様

### 1.1 結果収集 Job API

#### 入力

`POST /jobs/result-collections`

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

- `from_date`: 必須。収集開始日。
- `to_date`: 必須。収集終了日。`from_date <= to_date` を必須とする。
- `courses`: 必須。1件以上。要素は `CourseCode`。
- `storage`: 任意。`jsonl` または `sqlite`。省略時は環境変数 `JRA_SRB_RESULTS_STORAGE`、それも未設定なら `jsonl`。
- `output`: 任意。保存先パス。省略時は `JRA_SRB_RESULTS_PATH`、それも未設定なら `data/results.jsonl`。
- `retries`: 任意。0以上。省略時は 0。

#### 出力

`POST /jobs/result-collections`

- status code: `202 Accepted`
- response:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

`GET /jobs/result-collections`

- status code: `200 OK`
- response:

```json
{
  "items": [
    {
      "job_id": "uuid",
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
      "message": null,
      "error": null
    }
  ],
  "total": 1
}
```

`GET /jobs/result-collections/{job_id}`

- status code: `200 OK`
- response: 上記 item と同じ job 詳細。

#### 正常系

- `POST` は job を registry に登録し、非同期に `PastResultCollector.collect()` を実行する。
- job 登録直後は `queued`。
- 実行開始時に `running`、成功時に `succeeded`。
- `PastResultCollector` は既存仕様どおり、保存済み race_id は skip する。
- `GET` は現在プロセス内で保持している job の状態を返す。

#### 異常系

- `from_date > to_date`: 422 validation error。
- `courses` が空: 422 validation error。
- `storage` が `jsonl|sqlite` 以外: 422 validation error。
- `job_id` が存在しない: 404 `not_found`。
- 収集中に例外が発生した場合:
  - job status は `failed`。
  - `finished_at` を設定する。
  - `error` に例外メッセージを保存する。
  - API 全体は落とさない。

#### 副作用

- `output` で指定した JSONL または SQLite に結果を書き込む。
- registry はプロセス再起動で消える。

### 1.2 レース検索 API

#### 入力

`GET /search/races`

Query:

- `date`: 必須。開催日。
- `course`: 任意。`CourseCode`。未指定時は当日の全開催場を対象にする。
- `keyword`: 任意。部分一致検索。race_id、レース名、開催場、レース番号を対象にする。
- `limit`: 任意。1以上100以下。省略時100。
- `offset`: 任意。0以上。省略時0。

#### 出力

```json
{
  "items": [
    {
      "race_id": "202603220611",
      "date": "2026-03-22",
      "course": "nakayama",
      "race_no": 11,
      "race_name": "スプリングステークス",
      "start_time": "15:45"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

#### 正常系

- `course` 指定あり:
  - `JraService.get_races(date, course)` を呼ぶ。
- `course` 指定なし:
  - `JraService.get_races(date, None)` を呼ぶ。
- `keyword` 指定あり:
  - 大文字小文字を区別せず、以下を文字列化して部分一致する。
    - `race_id`
    - `race_number`
    - `name`
    - `course`
- `race_no` は `RaceSummary.race_number` の `11R` 形式から抽出できる場合のみ設定する。抽出できない場合は `null` を許容する。

#### 異常系

- `date` の形式不正: 422 validation error。
- `limit` 範囲外: 422 validation error。
- upstream 取得失敗: 既存 `ProviderError` handler に従い `upstream_error`。

#### 副作用

- 新規保存は行わない。
- 既存 service cache は利用される。

## 2. 既存構成における担当

- 入口:
  - `src/jra_srb/app.py`
- 入力 / 出力 DTO:
  - `src/jra_srb/models.py`
- 処理配置:
  - Job registry と job 実行補助は新規 `src/jra_srb/jobs.py`
  - レース検索のページング DTO は `models.py`
- データアクセス方式:
  - 結果収集は既存 `PastResultCollector` と `JsonlRaceResultStorage` / `SQLiteRaceResultStorage`
  - レース検索は既存 `JraService.get_races()`
- 表示 / 応答:
  - FastAPI response model を定義し OpenAPI に出す。
- 共通処理 / helper:
  - `get_result_storage()` と同じ storage 選択規則を job 用 helper へ切り出す。

## 3. 実装配置

- 追加ファイル:
  - `src/jra_srb/jobs.py`
- 修正ファイル:
  - `src/jra_srb/app.py`
  - `src/jra_srb/models.py`
  - `tests/test_api.py`
  - `README.md`
  - `docs/jra/05_API仕様.md`
- 既存流用:
  - `PastResultCollector`
  - `JsonlRaceResultStorage`
  - `SQLiteRaceResultStorage`
  - `JraService.get_races()`
  - `CourseCode`
- 新規抽象化の有無と理由:
  - `jobs.py` は必要。in-memory registry、状態遷移、非同期実行を `app.py` に直書きすると endpoint が肥大化するため。
  - storage factory helper は必要。API と Job API の保存先選択規則を揃えるため。

## 4. 根拠

| 判断 | 根拠ファイル | 備考 |
| --- | --- | --- |
| 結果収集は既存 collector を使う | `src/jra_srb/batch.py` | `PastResultCollector.collect(from_date, to_date, courses)` が存在する |
| 保存先は JSONL / SQLite を許容する | `src/jra_srb/batch.py`, `src/jra_srb/app.py` | 両 storage と env 選択が既にある |
| レース検索は service の既存一覧取得を使う | `src/jra_srb/service.py` | `get_races(target_date, course)` が存在する |
| エラー形式は標準 handler に合わせる | `src/jra_srb/app.py` | `error_response()` と exception handlers が存在する |

## 5. エラー / ログ / 設定

- エラー処理:
  - validation は Pydantic / FastAPI に任せる。
  - job not found は `LookupError` を投げ、既存 handler で 404 にする。
  - job 内例外は registry に保存し、endpoint の例外にはしない。
- ログ:
  - job 作成時、開始時、成功時、失敗時に `logger.info` / `logger.exception` を出す。
  - `job_id`, `from_date`, `to_date`, `courses`, `storage`, `output` を `extra` に含める。
- 設定:
  - `JRA_SRB_RESULTS_STORAGE`
  - `JRA_SRB_RESULTS_PATH`
  - `JRA_SRB_UPSTREAM_MAX_CONCURRENCY`
  - `JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS`
- 機密情報の扱い:
  - 今回の追加機能では secret は扱わない。

## 6. Reference との差分

| Reference 仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| Job API は P1 候補 | 既存 `.workstate` に P1 として記載あり | 採用 |
| registry は最初 in-memory でよい | 永続 job store は現行コードに存在しない | 採用 |
| レース検索 API は新規提案 | `get_races` が既に一覧取得を提供している | 小さく採用 |

## 7. テスト観点

- 自動テスト:
  - `POST /jobs/result-collections` が 202 と `queued` を返す。
  - job 成功後に `GET /jobs/result-collections/{job_id}` が `succeeded` を返す。
  - collector 例外時に job が `failed` になり `error` を保持する。
  - 未知の job_id が 404 を返す。
  - `GET /search/races` が date/course/keyword/limit/offset で期待通り絞り込む。
  - OpenAPI schema に新規 response model が出る。
- 手動確認:
  - Swagger UI で job 作成、一覧、詳細を確認する。
  - JSONL と SQLite の両方で保存結果が `/stored/results` から読めることを確認する。
- 回帰確認:
  - 既存 `tests/test_api.py`, `tests/test_batch.py`, `tests/test_service.py` が通る。

## 8. 対象外

- job registry の永続化。
- job cancel / retry API。
- 複数 worker / 複数プロセス間での job 共有。
- API key / CORS。
- public response DTO の全面安定化。
- 馬名、騎手名、払戻、オッズによる横断検索。
- 保存済み結果の集計 API。

## 9. 要確認事項

- `BackgroundTasks` で十分か、`asyncio.create_task()` を使うかは実装時にテスト容易性で決める。
- job の同時実行数制限は今回入れない。必要なら次タスクで `JRA_SRB_JOB_MAX_CONCURRENCY` を追加する。
