# 010-race-grade-persistence実装仕様書

## 0. 最初に読む要約

- 対象機能: JRAレース格付けの取得・保存。
- 改修目的: JRA公式会場一覧の格付けを `race_grade` として一貫して扱う。
- 現行仕様の要点: 格付けはHTMLに存在するがモデル・API・SQLiteへ流れていない。
- 最重要注意点: スカウトの `grade` とレースの `race_grade` を混同せず、未格付けを推測補完しない。

## 1. 変更後仕様

- 入力: 会場一覧HTMLの `td.race_name` 配下の `grade_icon`。
- 正規化結果: `G1`、`G2`、`G3`、`Jpn1`、`Jpn2`、`Jpn3`、`J.G1`、`J.G2`、`J.G3`、`L`、`OP`。認識できない表示または格付けなしは `None`。
- 出力: `MeetingRace.race_grade` を `GET /meetings/{date}/{course}` の各レースに含める。
- 保存: `races.race_grade TEXT NULL` を追加し、会場一覧保存時にUPSERTする。カード保存・予想保存によるUPSERTは既存の非NULL格付けを消去しない。
- 正常系: 公式HTMLの画像 `alt` とテキスト双方から格付けを抽出する。
- 異常系: HTMLに格付け要素がない、または未知の表記なら `None` を返し、取得全体を失敗させない。

## 2. 既存構成における担当

- 入口: `parse_meeting_races`。
- モデル: `MeetingRace` の任意フィールド追加。
- データアクセス: `AnalysisSQLiteStore.init_db`、`write_race`、`write_card`。
- API: 既存 `MeetingSnapshot` のPydantic直列化で公開するため、新規ルートは不要。

## 3. 実装配置

- 修正: `src/jra_srb/models.py`、`src/jra_srb/extractors.py`、`src/jra_srb/analysis_store.py`。
- 修正テスト: `tests/test_extractors.py`、`tests/test_analysis_store.py`、必要最小限の `tests/test_api.py`。
- 追加ファイル: なし。
- 新規抽象化: なし。抽出関数は `extractors.py` 内の小さな非公開helperに留める。

## 4. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| 一覧パーサーで抽出する | `extractors.py` | 289-329 | HTML行単位の情報源 |
| モデルに追加する | `models.py` | 224-238 | API応答の型 |
| DB列とUPSERTを追加する | `analysis_store.py` | 74-92, 701-739, 809-855 | 既存保存経路 |
| 後方互換の列追加を使う | `analysis_store.py` | 513-529, 3350-3353 | 既存方式 |

## 5. エラー / ログ / 設定

- エラー: 格付け未検出はエラーにしない。
- ログ: 新規ログは追加しない。
- 設定: 追加しない。
- 機密情報: 扱わない。

## 6. Referenceとの差分

| Reference仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| reference利用 | reference rootなし | 実コードだけを正とする |

## 7. テスト観点

- パーサー: G3画像alt、OPテキスト、格付けなしの3ケース。
- API: 会場一覧応答で `race_grade` が直列化される。
- SQLite: 新規DBに列ができ、既存想定DBにも初期化で列が追加される。
- UPSERT: `write_race` が格付けを保存し、格付けなしの `write_card` が保存済み値を消さない。

## 8. 対象外

- レース名からの格付け推定。
- 過去レースの一括バックフィル。
- スカウト評価の `grade` の名称変更。
- 南関競馬の格付け対応。

## 9. 要確認事項

- JRAの未知の表示形式は `None` とし、実データで確認でき次第正規化表へ追加する。
