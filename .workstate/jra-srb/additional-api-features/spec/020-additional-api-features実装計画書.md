# 020-additional-api-features 実装計画書

## 1. 対象と目的

- 対象機能:
  - 結果収集 Job API
  - レース検索 API
- 改修目的:
  - 長時間の過去結果収集を API から job として扱えるようにする。
  - race_id を知らない利用者が、開催日・開催場・キーワードからレースを探せるようにする。
- 今回の対象範囲:
  - in-memory job registry
  - job 作成 / 一覧 / 詳細取得
  - 既存 collector を使った結果収集
  - `GET /search/races`
  - response model とテスト
- 今回やらないこと:
  - job 永続化
  - job cancel
  - 認証 / CORS
  - 保存済み結果の分析 API
  - 内部 model と public DTO の全面分離

## 2. 実装フェーズ

### Phase 1: 事前確認

- 既存 `PastResultCollector`、storage、`JraService.get_races()` の現行テストを確認する。
- Windows 実行時は `.venv-win` と `uv` を使う。

### Phase 2: モデル追加

- `models.py` に Job API とレース検索 API の request / response model を追加する。
- status は `queued`, `running`, `succeeded`, `failed` の enum にする。

### Phase 3: job registry 実装

- `jobs.py` を追加する。
- in-memory dict で job を保持する。
- `create_result_collection_job()`, `list_jobs()`, `get_job()`, `run_job()` 相当の責務を持たせる。
- job の状態遷移と error 保存を registry 内で完結させる。

### Phase 4: API endpoint 追加

- `app.py` に `jobs` tag と `search` tag を追加する。
- `POST /jobs/result-collections`
- `GET /jobs/result-collections`
- `GET /jobs/result-collections/{job_id}`
- `GET /search/races`

### Phase 5: テスト

- API テストを中心に追加する。
- 実 upstream に依存しないよう fake service / fake collector / dependency override を使う。
- full test を実行する。

### Phase 6: ドキュメント

- README に新 API の使い方を追記する。
- `docs/jra/05_API仕様.md` に endpoint 契約を追記する。

## 3. タスク一覧

| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | Phase 1 | 既存 collector / storage / service の契約確認 | `batch.py`, `service.py`, tests | 実装前メモ | なし | 変更対象が確定している |
| T02 | Phase 2 | Job API model を追加 | 仕様書 | `models.py` | T01 | request / response model が型定義される |
| T03 | Phase 2 | Race search model を追加 | 仕様書 | `models.py` | T01 | page response model が型定義される |
| T04 | Phase 3 | `jobs.py` を追加 | `PastResultCollector`, storage | job registry | T02 | 状態遷移を単体でテストできる |
| T05 | Phase 4 | Job endpoint を追加 | `jobs.py` | `app.py` | T04 | POST/GET が動く |
| T06 | Phase 4 | Race search endpoint を追加 | `JraService.get_races()` | `app.py` | T03 | keyword/paging が動く |
| T07 | Phase 5 | API テストを追加 | endpoint | `tests/test_api.py` | T05,T06 | job/search の主要ケースを固定 |
| T08 | Phase 5 | 回帰テスト実行 | test suite | 結果ログ | T07 | full test が通る |
| T09 | Phase 6 | README / API docs 更新 | 実装済み endpoint | docs | T05,T06 | 利用例が追記される |

## 4. 完了判定

- 実装完了条件:
  - API から結果収集 job を作成できる。
  - job_id で状態確認できる。
  - job 一覧を取得できる。
  - API からレース検索できる。
- テスト完了条件:
  - `uv run --extra dev pytest -q` が Windows `.venv-win` で通る。
  - 実 upstream に依存しないテストになっている。
- レビュー完了条件:
  - 既存 API の URL とレスポンス互換を壊していない。
  - request_id 付き標準エラー形式を維持している。
  - job 失敗時に API プロセスが落ちない。

## 5. 別タスク候補

- Job registry の SQLite 永続化。
- Job cancel / retry endpoint。
- `JRA_SRB_JOB_MAX_CONCURRENCY` による job 同時実行制限。
- API key guard / CORS。
- 保存済み結果の統計 API。
- 馬名・騎手名・払戻・オッズ横断検索。
- public response DTO 安定化。
