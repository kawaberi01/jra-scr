# 000-additional-api-features 前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: JRA レース情報 API の追加機能
- 改修目的: API 利用者が「長時間の結果収集」と「開催日のレース探索」を HTTP API から扱えるようにする。
- 関連 API / バッチ:
  - `POST /jobs/result-collections`
  - `GET /jobs/result-collections`
  - `GET /jobs/result-collections/{job_id}`
  - `GET /search/races`
  - 既存 `PastResultCollector`
  - 既存 `/races`, `/meetings`, `/stored/results`

## 2. 入力情報

- ユーザー要件:
  - API の機能として増やした方が良い機能を検討する。
  - スキルを使って追加機能の実装仕様を固める。
- reference_status: 外部 reference は未使用。実コードと既存 `.workstate` を正とする。
- 読み込んだ reference: なし。
- 参照した既存資料:
  - `.workstate/jra-srb/api-quality-next-tasks/spec/020-api-quality-next-tasks実装計画書.md`
  - `.workstate/jra-srb/api-quality-next-tasks/spec/030-api-quality-next-tasks実装指示書.md`
- 参照した主要コード:
  - `src/jra_srb/app.py`
  - `src/jra_srb/batch.py`
  - `src/jra_srb/models.py`
  - `src/jra_srb/service.py`

## 3. 作成する成果物

- `000-additional-api-features前提メモ.md`
- `010-additional-api-features実装仕様書.md`
- `020-additional-api-features実装計画書.md`
- `030-additional-api-features実装指示書.md`

## 4. 注意点

- 今回は仕様固定のみを行い、コード実装は行わない。
- 既存 API の URL、レスポンス互換、保存形式を壊さない。
- 長時間処理を HTTP request 内で同期完了させる設計にはしない。
- 最初の Job API は in-memory registry とし、永続化・キャンセル・再起動後復元は別タスクに分離する。
- レース検索 API は既存の `JraService.get_races()` / `get_meeting()` で取れる範囲に限定し、馬名・騎手名・払戻条件による横断検索は別タスクに分離する。
