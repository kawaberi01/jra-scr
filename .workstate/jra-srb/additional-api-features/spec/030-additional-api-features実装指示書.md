# 030-additional-api-features 実装指示書

## 1. 対象概要

- 対象機能:
  - 結果収集 Job API
  - レース検索 API
- 改修目的:
  - 収集処理を API request から切り離して job として追跡可能にする。
  - race_id を知らない状態でも対象レースを探せる API を追加する。
- この機能が行う処理:
  - API から collector を起動する。
  - job 状態をプロセス内 registry に記録する。
  - 既存 service のレース一覧を検索・ページングして返す。
- 変更してよい範囲:
  - `src/jra_srb/app.py`
  - `src/jra_srb/models.py`
  - `src/jra_srb/jobs.py`
  - `tests/test_api.py`
  - 必要に応じて `tests/test_batch.py`
  - `README.md`
  - `docs/jra/05_API仕様.md`
- 変更してはいけない範囲:
  - 既存 endpoint の URL 変更。
  - 既存 JSONL / SQLite 保存形式の破壊。
  - JRA HTML parser の仕様変更。
  - API key / CORS / DTO 全面分離を同時に混ぜること。

## 2. 実装順序

1. `models.py` に request / response model を追加する。
2. `jobs.py` を追加し、in-memory registry と状態遷移を実装する。
3. storage factory helper を `app.py` から利用しやすい形に整理する。
4. `app.py` に Job API endpoint を追加する。
5. `app.py` に Race search endpoint を追加する。
6. fake service / fake collector を使って API テストを追加する。
7. README と `docs/jra/05_API仕様.md` を更新する。
8. full test を実行する。

## 3. 追加 / 修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 追加 | `src/jra_srb/jobs.py` | job registry、状態遷移、collector 実行 |
| 修正 | `src/jra_srb/models.py` | Job / Search DTO と enum 追加 |
| 修正 | `src/jra_srb/app.py` | endpoint、tag、dependency 追加 |
| 修正 | `tests/test_api.py` | Job API / Search API テスト |
| 修正 | `README.md` | 使い方追記 |
| 修正 | `docs/jra/05_API仕様.md` | API 契約追記 |

## 4. 実装ルール

- 既存構成にない大きな layer 分離は追加しない。
- `jobs.py` は小さく保ち、collector と storage の既存実装を再利用する。
- job registry は module global でよいが、テストで差し替え・初期化できるようにする。
- job status は文字列直書きではなく enum / `Literal` / `StrEnum` のいずれかで固定する。
- `POST /jobs/result-collections` は `202 Accepted` を返す。
- job 実行中の例外は握りつぶさず、ログに出し、job record の `error` に残す。
- `GET /search/races` は保存済み結果を読まず、live/list API の検索に限定する。
- `keyword` 検索はまず単純な case-insensitive 部分一致に限定する。
- 実 upstream へアクセスするテストは禁止。dependency override か fake provider を使う。

## 5. タスク詳細

| 順序 | タスク名 | 内容 | 入力 | 出力 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | DTO 追加 | `ResultCollectionJobRequest`, `ResultCollectionJobSummary`, `ResultCollectionJobPage`, `RaceSearchItem`, `RaceSearchPage` を追加 | 010 仕様 | `models.py` | OpenAPI に出せる |
| 2 | Registry 追加 | job 作成・一覧・取得・実行を実装 | `PastResultCollector` | `jobs.py` | 成功/失敗状態を保持できる |
| 3 | Storage factory 整理 | `jsonl|sqlite` 選択を Job API でも使えるようにする | `get_result_storage()` | helper | API と job の保存先規則が一致 |
| 4 | Job endpoint 追加 | POST/GET endpoints を追加 | registry | `app.py` | 202/200/404 が期待通り |
| 5 | Search endpoint 追加 | `JraService.get_races()` を検索・ページング | service | `app.py` | keyword/limit/offset が期待通り |
| 6 | テスト追加 | fake を使って主要ケースを固定 | endpoint | tests | 外部通信なしで通る |
| 7 | docs 更新 | README/API 仕様追記 | endpoint | docs | curl 例がある |
| 8 | 検証 | `uv run --extra dev pytest -q` | test suite | result | 全テスト成功 |

## 6. レビュー観点

- `POST /jobs/result-collections` が同期的に collector 完了まで待っていないか。
- job 失敗時に `failed` と `error` が記録されるか。
- `from_date > to_date` や空 `courses` が validation で止まるか。
- storage 選択規則が API と CLI の用語からずれていないか。
- `GET /search/races` が upstream に余計な重複アクセスを増やしていないか。
- 既存 `/races`, `/meetings`, `/stored/results` の挙動を壊していないか。

## 7. 禁止事項

- parser を修正して検索機能を実現すること。
- job registry 永続化を今回混ぜること。
- cancel API を今回混ぜること。
- 認証・CORS を今回混ぜること。
- 実 upstream に依存するテストを追加すること。
- `.venv` を Windows 用に作り替えること。Windows では `.venv-win` を使う。
