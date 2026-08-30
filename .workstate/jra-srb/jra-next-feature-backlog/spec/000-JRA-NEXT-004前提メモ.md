# 000-JRA-NEXT-004前提メモ

## 1. 対象

- 対象 root: `D:\\develop\\jra-scr`
- 対象機能: 結果収集 Job registry の SQLite 永続化
- 改修目的: API プロセスを再起動しても Job の一覧、詳細、最終状態を参照可能にする。
- 関連 API: `POST /jobs/result-collections`、`GET /jobs/result-collections`、`GET /jobs/result-collections/{job_id}`

## 2. 入力情報

- ユーザー要件: JRA-NEXT-004 をスキルに従って実装し、進捗を更新する。
- reference_status: 実コードで裏取り済み。
- 参照した既存資料: 共通バックログ `progress/001` から `007`。
- 参照した主要コード: `src/jra_srb/jobs.py`、`src/jra_srb/app.py`、`src/jra_srb/models.py`、`tests/test_api.py`、`src/jra_srb/batch.py`。

## 3. 作成する成果物

- `005-JRA-NEXT-004現行仕様整理.md`
- `010-JRA-NEXT-004実装仕様書.md`
- `020-JRA-NEXT-004実装計画書.md`
- `030-JRA-NEXT-004実装指示書.md`

## 4. 注意点

- 既存の公開 API パスと response model は変更しない。
- プロセス停止時に実行中だった Job は再開しない。起動時に失敗へ確定し、誤って実行中表示を残さない。
