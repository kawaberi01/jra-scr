# 000-race-grade-persistence前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: JRAレース格付けの取得・API公開・SQLite保存
- 改修目的: JRA会場一覧にある競走格付けを、スカウト評価の `A/B/C/X` とは別に `races.race_grade` として保持する。
- 関連: `GET /meetings/{date}/{course}`、JRA収集、オッズ時系列収集、analysis SQLite。

## 2. 入力情報

- ユーザー要件: レースのグレードを保存するカラムを追加する。
- reference_status: unavailable。router指定の reference root はWindows環境に存在しない。
- 参照した主要コード: `models.py`、`extractors.py`、`analysis_store.py`、`analysis_collector.py`、`jra_odds_timeline.py`、関連テスト。

## 3. 作成する成果物

- `005-race-grade-persistence現行仕様整理.md`
- `010-race-grade-persistence実装仕様書.md`
- `020-race-grade-persistence実装計画書.md`
- `030-race-grade-persistence実装指示書.md`

## 4. 注意点

- `jra_scout_entries.grade` はスカウト評価であり、レース格付けに流用しない。
- 既存SQLiteへは `_ensure_column` を使う後方互換方式で列追加する。
- 既存の未格付けレースは `NULL` のまま保持し、名称から推測して埋めない。
