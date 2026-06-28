# 000-analysis-sqlite-local-db 前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: 分析用ローカル SQLite DB 収集機能
- 改修目的: 自己改良エージェントが、過去レースの発走前情報、オッズ、結果、払戻、予想、評価結果を再現可能に扱えるようにする。
- 関連資料:
  - `docs/nakaana_self_learning_agent_spec.md`
- 関連コード:
  - `src/jra_srb/service.py`
  - `src/jra_srb/batch.py`
  - `src/jra_srb/models.py`
  - `src/jra_srb/jobs.py`

## 2. 入力情報

- ユーザー要件:
  - 分析用ローカルDBとして SQLite を実装したい。
  - 主にオッズを見ている想定。
  - 自己改良エージェントに使えるデータを収集したい。
- reference_status:
  - 外部 reference は未使用。
  - `docs/nakaana_self_learning_agent_spec.md` を構想 reference として扱う。
  - 実コードを正として、取得可能なデータ範囲を決める。

## 3. 判断の前提

- 一次保存は SQLite にする。
- CSV / Parquet は分析基盤連携用の export として後続タスクに分ける。
- Prediction Agent に渡すデータは発走前情報だけに限定する。
- 結果・払戻は Evaluator 専用テーブルに分離する。
- LLM 出力は JSON schema validation 可能な JSON として保存する。
- 的中判定は LLM ではなく deterministic code で行う。

## 4. 注意点

- 現行 `SQLiteRaceResultStorage` は `result_json` 丸ごと保存で、分析用正規化DBとしては不足。
- オッズは「いつ取得したか」が重要。最初は `final_or_near_final` 相当として保存し、将来 snapshot timing を拡張できるようにする。
- 結果リーク防止のため、発走前 snapshot と結果 / 払戻を同じ取得 job で保存しても、API/MCP の返却口は分ける。
