# 030-analysis-sqlite-local-db 実装指示書

## 1. 対象概要

- 対象機能: 分析用 SQLite DB 収集機能
- 変更してよい範囲:
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/analysis_collector.py`
  - `src/jra_srb/cli.py`
  - `tests/test_analysis_store.py`
  - `tests/test_analysis_collector.py`
  - `README.md`
  - `docs/jra/05_API仕様.md`
  - `docs/nakaana_self_learning_agent_spec.md`
- 変更してはいけない範囲:
  - 既存 `SQLiteRaceResultStorage` の互換破壊
  - 既存 API endpoint のURL変更
  - 既存 parser の仕様変更

## 2. 実装ルール

- SQLite は標準 `sqlite3` を使う。
- 収集データは upsert 可能にする。
- 発走前情報と結果情報を同じ response helper で混ぜない。
- オッズの数値変換に失敗した場合は nullable とし、元文字列が必要なら JSON payload 側に残す。
- `collection_errors` は失敗しても処理継続できるよう race/stage 単位で保存する。
- テストは fixture / fake service を使い、実 upstream にアクセスしない。

## 3. 実装順序

1. `AnalysisSQLiteStore` を作成し、schema を定義する。
2. race/card/runner/odds/result/payout/error の保存メソッドを追加する。
3. `AnalysisCollector` を追加し、meeting -> card -> odds -> result の順に保存する。
4. CLI に `collect-analysis` を追加する。
5. `get_pre_race_snapshot(race_id)` 相当の store メソッドを追加し、結果情報が入らないことをテストする。
6. docs を更新する。

## 4. 最初のCLI仕様

```bash
jra-srb collect-analysis \
  --from-date 2026-03-22 \
  --to-date 2026-03-22 \
  --courses nakayama \
  --db data/analysis.sqlite \
  --include-card \
  --include-odds \
  --include-results \
  --retries 1
```

## 5. テスト観点

- schema 作成。
- 1 race の card / odds / result / payouts 保存。
- 同じ race の再保存で重複しない。
- odds_entries の `bet_type`, `combination`, `odds`, `popularity` が検索できる。
- `pre_race_snapshot` に result / payout が含まれない。
- result 取得失敗時に `collection_errors` が保存される。

## 6. 禁止事項

- CSVを一次保存にすること。
- 結果・払戻を Prediction Agent 入力へ混ぜること。
- LLMによる的中判定を今回実装すること。
- 自己改良エージェント本体を今回実装すること。
