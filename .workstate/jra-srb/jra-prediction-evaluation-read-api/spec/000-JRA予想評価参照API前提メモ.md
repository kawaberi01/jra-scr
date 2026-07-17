# 000-JRA予想評価参照API前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: JRA予想・評価参照API
- 改修目的: SQLiteへ保存済みの予想、予想券、評価、評価券結果をHTTP APIから詳細・一覧・集計として参照可能にする。
- 関連API: `POST /jra/meetings/{date_}/{course}/races/{race_no}/predictions`、`POST /jra/predictions/{prediction_id}/evaluate`
- 関連DB: `analysis.sqlite`の`predictions`、`prediction_tickets`、`evaluations`、`evaluation_ticket_results`、`races`

## 2. 入力情報

- ユーザー要件: API群・CLI群の不足を優先度順に仕様化し、仕様完了後にスキルで実装する。今回は最優先の予想・評価参照APIを1機能として扱う。
- reference_status: `not_found`
- 読み込んだreference: なし。reference候補はOZ/.NET系であり、本Python/FastAPIプロジェクトには適用しない。
- 参照した既存資料: `README.md`、`docs/jra/05_API仕様.md`、`docs/jra/12_予想エージェント評価プロトコル.md`
- 参照した主要コード: `src/jra_srb/app.py`、`src/jra_srb/analysis_store.py`、`src/jra_srb/models.py`、`tests/test_api.py`、`tests/test_analysis_store.py`

## 3. 作成する成果物

- `005-JRA予想評価参照API現行仕様整理.md`
- `010-JRA予想評価参照API実装仕様書.md`
- `020-JRA予想評価参照API実装計画書.md`
- `030-JRA予想評価参照API実装指示書.md`

## 4. 注意点

- 実コードを正本とし、既存の作成・評価挙動、DBスキーマ、JSON保存形式を変更しない。
- 読み取り専用APIのみを追加し、予想生成ロジックや評価計算ロジックを変更しない。
- 現在の作業ツリーには既存の未コミット変更があるため、対象ファイルの既存差分を保持する。
- 仕様作成フェーズではビルド、テスト、アプリ起動、DB接続を行わない。

