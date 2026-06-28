# 005-analysis-sqlite-local-db 現行仕様整理

## 1. 現行の収集・保存

- `PastResultCollector` は日付範囲と開催場を受け、meeting 一覧から各レース結果を取得する。
- 保存先は `JsonlRaceResultStorage` または `SQLiteRaceResultStorage`。
- 現行 SQLite は `race_results` に `race_id`, `race_date`, `course`, `race_no`, `result_json` を保存する。
- `result_json` は再取得には便利だが、オッズ、出走馬、予想、評価、失敗履歴の分析には向かない。

## 2. 現行で取得できるデータ

### 発走前側

- `MeetingSnapshot`
  - date
  - course
  - races
  - start_time
  - race_id
- `RaceCard`
  - race_name
  - course
  - distance
  - surface
  - start_time
  - runners
  - runner odds / popularity
- `RaceOdds`
  - bet_type
  - entries
  - combination
  - odds / odds_min / odds_max
  - popularity

### 結果側

- `RaceResult`
  - result entries
  - payouts
  - rank
  - horse_no
  - payout
  - popularity

## 3. 自己改良エージェント仕様とのギャップ

- `get_pre_race_snapshot` 相当の保存・返却口がない。
- 発走前情報と結果情報をDBスキーマ上で分離していない。
- 予想JSON、評価JSON、理論バージョン、検証セットを保存するテーブルがない。
- 収集失敗理由を race_id 単位で残す専用テーブルがない。
- オッズ中心分析に必要な `odds_snapshots` と `odds_entries` が正規化されていない。
- 回収率、的中率、ガミ率などを集計しやすい評価テーブルがない。

## 4. 実装方針

- 既存 `SQLiteRaceResultStorage` は互換維持のため壊さない。
- 新規に `AnalysisSQLiteStore` を追加する。
- 収集対象は最初の実装では以下に絞る。
  - meeting / race metadata
  - race card / runners
  - odds snapshots / odds entries
  - race results / result entries
  - payouts
  - collection errors
  - predictions
  - evaluations
  - theory versions
- CSV / Parquet export はDB保存後の別機能にする。
