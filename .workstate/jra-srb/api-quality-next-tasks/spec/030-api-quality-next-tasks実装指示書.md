# API 品質追加改修 実装指示書

## 最初に実装する対象

P0:

- Storage backend 設定統一
- Upstream アクセス制御

## 変更してよい範囲

- `src/jra_srb/app.py`
- `src/jra_srb/provider.py`
- `src/jra_srb/service.py`
- `src/jra_srb/batch.py`
- `tests/test_api.py`
- `tests/test_provider.py`
- `README.md`
- `docs/jra/05_API仕様.md`

## 変更してはいけない範囲

- 既存 endpoint の URL 変更
- 既存 JSONL 保存形式の破壊
- JRA HTML parser の仕様変更
- API key / CORS / job API まで同時に混ぜること

## 実装手順

1. `get_result_storage()` に `JRA_SRB_RESULTS_STORAGE` を追加する。
2. `jsonl` と `sqlite` を許容する。
3. 不正値の扱いを決める。
4. API storage の SQLite 読み出しテストを追加する。
5. `HttpProvider` に `max_concurrency` と `min_interval_seconds` を追加する。
6. app の `build_service()` で環境変数から provider を構築する。
7. provider の throttle / semaphore テストを追加する。
8. README / API 仕様へ環境変数を追記する。

## テスト観点

- `JRA_SRB_RESULTS_STORAGE=sqlite` で `GET /stored/results/{race_id}` が読める。
- `JRA_SRB_RESULTS_STORAGE=bad` は標準エラー形式で失敗する。
- `HttpProvider(max_concurrency=1)` が設定できる。
- `min_interval_seconds` 指定時に sleep が呼ばれる。
- 既存 API テストが通る。

## 停止条件

- upstream 制御の実装が event loop をまたいで不安定になる場合は、provider ごとのインスタンス内制御に留める。
- API key / CORS / job API は今回混ぜない。
