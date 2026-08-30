# 030-race-grade-persistence実装指示書

## 1. 対象概要

- 対象機能: JRAレース格付け保存。
- 改修目的: 公式会場一覧の格付けをAPI・SQLiteに正式保存する。
- 変更してよい範囲: `models.py`、`extractors.py`、`analysis_store.py`、対象テスト、当featureの`.workstate`。
- 変更してはいけない範囲: 予想順位・V90・スカウト評価・既存APIパス・過去データの一括更新。

## 2. 実装順序

1. `MeetingRace`へ`race_grade: str | None = None`を追加する。
2. `parse_meeting_races`で行内のgrade iconを読み、正規化値を`MeetingRace`へ渡す。
3. `races`作成SQLと`_ensure_column`に`race_grade text`を追加する。
4. `write_race`、`write_card`、`_upsert_race_context`のUPSERTで格付けを保存し、格付けなしの入力で既存値を消さない。
5. 抽出・API・SQLiteの最小テストを追加し、対象テストを実行する。

## 3. 追加 / 修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 修正 | `src/jra_srb/models.py` | `MeetingRace.race_grade` |
| 修正 | `src/jra_srb/extractors.py` | 格付け抽出・正規化 |
| 修正 | `src/jra_srb/analysis_store.py` | 列追加と全race UPSERT |
| 修正 | `tests/test_extractors.py` | HTML抽出テスト |
| 修正 | `tests/test_analysis_store.py` | 永続化・既存値維持テスト |
| 修正 | `tests/test_api.py` | 会場一覧APIの直列化テスト |

## 4. 実装ルール

- `race_grade` はJRA公式表記の正規化値のみを保存する。
- 未格付け・未知表記は`None`。レース名で補完しない。
- `jra_scout_entries.grade` は変更しない。
- `_ensure_column`により既存SQLiteを破壊せずに移行する。
- 格付けを持たないカード・予想コンテキストのUPSERTは、既存の`races.race_grade`を保持する。

## 5. タスク詳細

| 順序 | タスク名 | 内容 | 完了条件 |
| --- | --- | --- | --- |
| 1 | 型と抽出 | モデル追加、`alt`/テキストを正規化 | 値が会場一覧モデルに入る |
| 2 | SQLite | スキーマ・互換列・3経路のUPSERT | 値が保存・保持される |
| 3 | テスト | parser/store/APIテスト | 期待値が固定される |
| 4 | 検証 | 対象pytestと差分確認 | 不要変更なし |

## 6. レビュー観点

- G1/G2/G3、Jpn/J.G、L、OPの正規化が安定しているか。
- `None`が既存値を上書きしていないか。
- Pydanticの任意フィールド追加が既存テストのfixtureを壊していないか。

## 7. 禁止事項

- 大規模リファクタ、外部スクレイピング追加、DB全件更新、スカウト評価の変更。
- 格付けを予想・買い目の重みへ自動反映すること。
