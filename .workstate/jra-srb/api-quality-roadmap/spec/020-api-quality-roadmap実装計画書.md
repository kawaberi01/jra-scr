# API 品質向上ロードマップ 実装計画書

## 最優先 P0

### 1. API エラーレスポンスの標準化

現状:

- `{"detail": "..."}` が中心。
- FastAPI の 422 と独自 400/404/502 の形が揃っていない。
- クライアントが `code` や `request_id` で機械処理しにくい。

実装案:

- `ApiErrorResponse` モデルを追加する。
- 形式を統一する。

```json
{
  "error": {
    "code": "unsupported_bet_type",
    "message": "unsupported bet_type=foobar",
    "request_id": "..."
  }
}
```

完了条件:

- 独自例外と 422 のレスポンス形式を揃える。
- OpenAPI にエラーモデルが出る。
- 既存テストを新形式へ更新する。

### 2. README / docs / OpenAPI の同期

現状:

- README は前回更新済みだが、追加済みの `/normalize`, `/stored/results`, CLI, `JRA_SRB_CACHE_PATH`, `JRA_SRB_RESULTS_PATH`, `.venv-win` 運用が未反映。
- source 内の日本語説明は環境表示上文字化けして見える箇所があり、UTF-8 実体確認が必要。

実装案:

- README に追加機能を反映する。
- `docs/jra/05_API仕様.md` を現行 endpoint に同期する。
- 環境変数一覧を追加する。
- Windows / WSL の `uv` 実行方法を追記する。

完了条件:

- README だけで起動、テスト、CLI、保存済み結果 API、永続 cache が分かる。
- OpenAPI と README の endpoint 一覧が一致する。

### 3. 保存済み結果 API のページング・件数制限

現状:

- `GET /stored/results` は条件一致した全件を返す。
- JSONL backend では毎回全行読み込みになる。

実装案:

- `limit`, `offset` または `page`, `page_size` を追加する。
- 最大 `limit` を設定する。
- レスポンスを `{items,total,limit,offset}` 形式にする。
- SQLite backend は SQL 側で limit / offset する。

完了条件:

- 大量保存済み結果でも API レスポンスが無制限にならない。
- OpenAPI に制約が出る。

## 優先 P1

### 4. 結果収集を同期 API ではなく job として扱う

現状:

- CLI では収集できるが、API から収集 job を管理できない。
- 長時間処理の状態確認、停止、再実行の API がない。

実装案:

- `POST /jobs/result-collections` で収集 job を開始する。
- `GET /jobs/result-collections/{job_id}` で状態を見る。
- 最初は in-memory job registry でよい。
- 将来的に SQLite job registry へ拡張できる形にする。

完了条件:

- API 利用者が長時間収集を HTTP request に閉じ込めず扱える。
- 状態は `queued/running/succeeded/failed` を持つ。

### 5. レスポンス DTO の安定化

現状:

- 内部 Pydantic model をそのまま返す endpoint が多い。
- `source`, `cache_hit`, `fetched_at` など内部寄りの情報が常に出る。

実装案:

- public response model と internal model を分ける。
- `include_meta=true` のときだけ `source/cache_hit/fetched_at` を返す案を検討する。

完了条件:

- API 契約が内部実装変更に引きずられにくい。
- OpenAPI の response model が明示される。

### 6. storage backend の設定統一

現状:

- API は `JRA_SRB_RESULTS_PATH` で JSONL 固定。
- CLI は `--storage jsonl/sqlite` を選べる。
- API 側では SQLite 結果 storage を環境変数で選べない。

実装案:

- `JRA_SRB_RESULTS_STORAGE=jsonl|sqlite` を追加する。
- `JRA_SRB_RESULTS_PATH` と組み合わせて API storage を構築する。

完了条件:

- API / CLI で storage 選択の考え方が揃う。

## 優先 P2

### 7. rate limit / robots 配慮 / 同時実行制御

現状:

- retry / backoff はある。
- 呼び出し頻度や同時実行数の上限はない。

実装案:

- provider に host 単位の semaphore を持たせる。
- 最小 request interval を設定できるようにする。
- `JRA_SRB_UPSTREAM_MAX_CONCURRENCY`, `JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS` を追加する。

完了条件:

- 外部サイトへの過剰アクセスを抑止できる。

### 8. CORS / 認証 / 公開範囲の整理

現状:

- ローカル API 前提で、CORS や認証はない。
- 外部公開する場合の境界がない。

実装案:

- デフォルトはローカル利用を明記する。
- 必要に応じて `JRA_SRB_API_KEY` による簡易 API key guard を追加する。
- CORS は明示設定時のみ許可する。

完了条件:

- ローカル専用と外部公開時の設定差が明確になる。

### 9. observability の整理

現状:

- logging は追加済みだが、request_id や構造化出力設定はない。

実装案:

- request_id middleware を追加する。
- error response と log に同じ request_id を入れる。
- JSON log 出力オプションを追加する。

完了条件:

- 障害時に API レスポンスとログを突合できる。

## 推奨着手順

1. API エラーレスポンスの標準化
2. README / docs / OpenAPI の同期
3. 保存済み結果 API のページング・件数制限
4. storage backend の設定統一
5. request_id / observability 整理
6. rate limit / 同時実行制御
7. job API
8. public response DTO 分離
9. CORS / 認証 / 公開範囲整理

## 判断

次に実装するなら、まず P0 の 1-3 をまとめて行うのが最も効果が高い。理由は、現在の API は機能数は増えているが、公開 API としての契約、ドキュメント、保存済みデータの扱いがまだ粗いため。
