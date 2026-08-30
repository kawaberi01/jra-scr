# 005-race-grade-persistence現行仕様整理

## 現行仕様

- 会場一覧は `parse_meeting_races` が `td.race_name` からレース名、`td.time` から発走時刻を抽出し、`MeetingRace` を返す。
- `MeetingRace` はレース名・距離・馬場等を持つが、格付けフィールドを持たない。
- `AnalysisSQLiteStore.write_race` は会場一覧の情報を `races` へUPSERTする。`races` に格付け列はない。
- カード保存時も `races` をUPSERTするが、既存値を `coalesce` で保護している。
- `jra_scout_entries.grade` は候補の評価ランクで、JRAのG1/G2/G3等ではない。

## 根拠

| 事実 | 根拠 |
| --- | --- |
| `MeetingRace`に格付けなし | `src/jra_srb/models.py:224-238` |
| 一覧HTMLの格付け未抽出 | `src/jra_srb/extractors.py:289-329` |
| `races`に格付けなし | `src/jra_srb/analysis_store.py:74-92` |
| 既存DBへの列追加方式 | `src/jra_srb/analysis_store.py:513-529` |
| 会場一覧をDBへ書く収集経路 | `src/jra_srb/analysis_collector.py:82-85` |

## 要件との差分

- 追加するもの: `race_grade` の抽出、API応答、SQLite保存、既存DBへの自動列追加、テスト。
- 維持するもの: レース名、スカウト評価、既存APIパス、既存レコード。
