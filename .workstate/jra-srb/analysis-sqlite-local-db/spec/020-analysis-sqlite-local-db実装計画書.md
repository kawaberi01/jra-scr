# 020-analysis-sqlite-local-db 実装計画書

## 1. 対象と目的

- 対象: 分析用 SQLite DB 収集機能
- 目的: 自己改良エージェントが過去データを安全に検証できるよう、発走前データ、オッズ、結果、払戻、予想、評価を保存する基盤を作る。
- 今回の実装単位:
  - SQLite schema
  - `AnalysisSQLiteStore`
  - 分析用収集 CLI
  - 収集エラー保存
  - テスト

## 2. 推奨実装順

1. `src/jra_srb/analysis_store.py` を追加。
2. SQLite schema と `init_db()` を実装。
3. `write_race`, `write_card`, `write_odds`, `write_result`, `write_error` を実装。
4. `AnalysisCollector` を追加。
5. CLI に `collect-analysis` を追加。
6. fixture service を使うテストを追加。
7. README / API仕様 / 自己学習エージェント仕様へのリンクを更新。

## 3. タスク一覧

| ID | 作業 | 出力 | DoD |
| --- | --- | --- | --- |
| T01 | schema 実装 | `analysis_store.py` | 全テーブルが作成される |
| T02 | 書き込みAPI実装 | `AnalysisSQLiteStore` | race/card/odds/result/error を upsert できる |
| T03 | 収集器実装 | `AnalysisCollector` | 日付範囲・開催場で収集できる |
| T04 | CLI追加 | `collect-analysis` | SQLiteへ保存できる |
| T05 | テスト追加 | `tests/test_analysis_store.py`, `tests/test_analysis_collector.py` | 外部通信なしで通る |
| T06 | docs更新 | README/docs | 使い方とDB方針が分かる |

## 4. 完了条件

- fixture で1開催分を SQLite に保存できる。
- `odds_entries` に bet_type / combination / odds / popularity が保存される。
- `result_entries` と `payouts` が結果側テーブルに保存される。
- 失敗した race/stage を `collection_errors` に保存できる。
- `pre-race-snapshot` 相当の読み出しで結果・払戻が混ざらない。

## 5. 後続タスク

- CSV export
- Parquet export
- `/analysis/*` API
- deterministic evaluator
- Prediction JSON schema validation
- Theory Registry 管理CLI
- Job API 化
