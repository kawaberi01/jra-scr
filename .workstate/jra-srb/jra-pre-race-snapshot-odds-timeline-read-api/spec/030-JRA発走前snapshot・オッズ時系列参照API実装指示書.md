# 030-JRA発走前snapshot・オッズ時系列参照API実装指示書

## 1. 対象概要

- 対象機能: JRA発走前snapshot・オッズ時系列参照API
- 改修目的: 保存済み`analysis.sqlite`を安全なtyped GET APIで参照可能にする。
- この機能が行う処理:
  - race単位で保存済み発走前情報を返す。
  - 券種単位で保存済みオッズsnapshotを時間順に返す。
- 変更してよい範囲:
  - `src/jra_srb/models.py`
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/app.py`
  - `tests/test_analysis_store.py`
  - `tests/test_api.py`
  - `docs/jra/05_API仕様.md`
- 変更してはいけない範囲:
  - DB schemaとmigration
  - `JraOddsTimelineCollector`と`write_odds()`の保存契約
  - 外部provider/extractor
  - 予想・評価ロジック
  - MCP allowlist
  - Nankan/netkeiba API

## 2. 実装前に読む順序

1. 本書
2. `020-JRA発走前snapshot・オッズ時系列参照API実装計画書.md`
3. `010-JRA発走前snapshot・オッズ時系列参照API実装仕様書.md`
4. `progress/006-次回着手メモ.md`
5. 対象ファイルの限定diff

## 3. 実装順序

1. 対象ファイルの既存未コミット差分を確認する。
2. `models.py`へ保存済み参照専用modelを追加する。
3. `get_pre_race_snapshot()`を後方互換で拡張する。
4. `get_odds_timeline()`を追加する。
5. `app.py`へGET route 2本を追加する。
6. Store/APIテストを追加する。
7. `docs/jra/05_API仕様.md`を更新する。
8. 限定diffで対象外変更と既存差分の保持を確認する。

## 4. 追加・修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 修正 | `src/jra_srb/models.py` | 保存済みsnapshot/timeline response model |
| 修正 | `src/jra_srb/analysis_store.py` | snapshot filterとtimeline query |
| 修正 | `src/jra_srb/app.py` | GET route 2本 |
| 修正 | `tests/test_analysis_store.py` | Store契約・結果リーク防止 |
| 修正 | `tests/test_api.py` | HTTP契約・validation・MCP非公開 |
| 修正 | `docs/jra/05_API仕様.md` | 利用仕様 |

## 5. 実装ルール

- `010`のendpoint、query、response契約を変更しない。
- 既存にないRepository/Service層を追加しない。APIから既存StoreをDIする。
- responseはPydantic modelで固定し、raw DB dictをそのまま公開しない。
- `combination_json`を`json.loads()`し、公開名は`combination`とする。
- `fetched_at`はdatetimeへ、`race_date`はdateへ復元する。
- SQLの値はbindする。
- snapshotの時間順は`fetched_at ASC, snapshot_id ASC`。
- 最新snapshotは券種ごとに`fetched_at DESC, snapshot_id DESC`の先頭。
- 結果系テーブルをqueryしない。
- MCPの`MCP_OPERATION_IDS`へ追加しない。
- DB schema、index、収集時点ラベルを変更しない。
- 既存`get_pre_race_snapshot(race_id)`呼び出しを壊さない。

## 6. タスク詳細

| 順序 | タスク名 | 内容 | 完了条件 |
| ---: | --- | --- | --- |
| 1 | 差分保護 | 6対象ファイルの限定status/diffを確認 | ユーザー変更を識別済み |
| 2 | Model | `010`記載の7 modelを追加 | 公開型とoptionalが仕様一致 |
| 3 | Snapshot Store | `include_odds`と`odds_timing`を追加 | latest/timing/falseを返せる |
| 4 | Timeline Store | 券種・組み合わせをfilter | 時間順、欠測snapshot保持 |
| 5 | API | route、query、response_model追加 | 200/404/400/422契約一致 |
| 6 | Store test | DB seedで型・順序・リーク防止確認 | 010のStore観点を網羅 |
| 7 | API test | 一時DB経由でHTTP契約確認 | 010のAPI観点を網羅 |
| 8 | Docs | request例と制約を追加 | DB直接参照なしで利用可能 |
| 9 | Review | 限定diff、静的観点確認 | 対象外変更なし |

## 7. レビュー観点

- responseに`results`、`payouts`、`evaluations`がないか。
- `combination_json`が外部に出ていないか。
- `odds_timing`文字列順を時間順として使っていないか。
- latest選択が券種ごとになっているか。
- combination逆順をunordered券種だけ同一視しているか。
- combination指定でentryがないsnapshotを落としていないか。
- raceなしとoddsなしを混同していないか。
- `include_odds=false`で不要なodds queryをしていないか。
- 既存MCP tool一覧を変えていないか。
- 既存未コミット差分を巻き戻していないか。

## 8. 禁止事項

- 新規プロジェクト作成。
- DB migration、履歴テーブル、index追加。
- 外部通信、refresh query、リアルタイム配信。
- API実装と同時のcollector改修。
- `except Exception`でDBエラーを空応答へ変換すること。
- raw SQLへのquery文字列埋め込み。
- 仕様外の横断リファクタや文字コード変更。
- 既存ファイルの無関係な整形。

## 9. 停止条件

次の場合は推測で進めず、progressへ記録して停止する。

- 現行DB schemaが`010`記載と異なる。
- 対象箇所に競合する未コミット変更があり、安全に併合できない。
- responseから結果系情報を除外できない既存依存が判明した。
- 既存テストが、引数なし`get_pre_race_snapshot()`で全時点返却を厳密に要求しており、後方互換方針の選択が必要になった。

最後の条件が発生した場合は、既存メソッドを変えずに新規typed Storeメソッドを追加する案を優先候補として提示する。

## 10. 静的確認と人間への引き継ぎ

- 静的確認:
  - import、型名、route競合、error handler、SQL bind、並び順、対象外差分。
- 人間の実行候補:

```powershell
rtk uv run pytest -q "tests\test_analysis_store.py" "tests\test_api.py"
rtk uvx ruff check "src\jra_srb\models.py" "src\jra_srb\analysis_store.py" "src\jra_srb\app.py" "tests\test_analysis_store.py" "tests\test_api.py"
```

- 実行結果は`progress/005-検証メモ.md`へ追記する。
