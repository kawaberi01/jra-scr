# 020-JRA発走前snapshot・オッズ時系列参照API実装計画書

## 1. 対象と目的

- 対象機能: JRA発走前snapshot・オッズ時系列参照API
- 改修目的: SQLite直接参照なしで保存済み発走前情報とオッズ推移を参照する。
- 今回の対象範囲: GET API 2本、Store拡張、Pydantic model、Store/APIテスト、API仕様書。
- 今回やらないこと: DB変更、収集処理変更、外部取得、MCP公開、コード実装以外の技術刷新。

## 2. 実装フェーズ

### Phase 1: 事前確認

- 本仕様の`030`と`020`を読む。
- 対象6ファイルの限定diffを確認し、既存未コミット変更との競合を把握する。

### Phase 2: 応答モデル

- 保存済み数値型に合わせた発走前・オッズ応答modelを追加する。
- DB内部列を公開modelから除外する。

### Phase 3: Store

- 既存`get_pre_race_snapshot()`を後方互換で拡張する。
- `get_odds_timeline()`を追加する。
- 結果系テーブルをqueryしないこと、時間順、券種別組み合わせ正規化を固定する。

### Phase 4: API

- race_idベースのGET routeを2本追加する。
- response model、summary、query制約、既存Store DIを設定する。
- MCP allowlistは変更しない。

### Phase 5: テスト・文書

- StoreとAPIの正常系・空・404・400・422・リーク防止を追加する。
- `docs/jra/05_API仕様.md`へ2 endpointと制約を追記する。

### Phase 6: レビュー・完了確認

- 対象外変更、結果リーク、時系列順、型変換、既存差分保持を静的確認する。
- テスト実行は人間へ引き継ぐ。

## 3. タスク一覧

| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | 事前確認 | 仕様・限定diff確認 | 030/020、git diff | 競合判断 | なし | 既存変更を識別済み |
| T02 | Model | 参照用model追加 | 010 | `models.py` | T01 | 全公開項目が型定義済み |
| T03 | Store | snapshot拡張 | T02、既存method | `analysis_store.py` | T02 | latest/timing/include_oddsが動作 |
| T04 | Store | timeline追加 | T02、DB schema | `analysis_store.py` | T02 | 時間順・filter・空応答が動作 |
| T05 | API | GET 2本追加 | T03/T04 | `app.py` | T03,T04 | response_modelとvalidation設定済み |
| T06 | Test | Store/API test追加 | T03-T05 | test code | T05 | 010記載ケースを網羅 |
| T07 | Docs | API仕様更新 | T05 | `05_API仕様.md` | T05 | request/response/制約を記載 |
| T08 | Review | 静的自己レビュー | 全変更 | review結果 | T06,T07 | 対象外混入なし |
| T09 | Verify | 人間がtest/lint実行 | T08 | 実行結果 | T08 | 全対象check成功 |

## 4. 完了判定

- 実装完了条件:
  - GET API 2本が保存済みSQLiteだけを読む。
  - typed responseにDB内部列と結果系情報が露出しない。
  - timelineが`fetched_at`順で、券種・組み合わせfilterを満たす。
- テスト完了条件:
  - 010記載のStore/APIテストが追加され、人間の実行で成功する。
- レビュー完了条件:
  - DB、collector、MCP allowlist、既存参照APIの契約を変更していない。

## 5. 人間へ引き継ぐ確認コマンド候補

```powershell
rtk uv run pytest -q "tests\test_analysis_store.py" "tests\test_api.py"
rtk uvx ruff check "src\jra_srb\models.py" "src\jra_srb\analysis_store.py" "src\jra_srb\app.py" "tests\test_analysis_store.py" "tests\test_api.py"
```

## 6. 別タスク候補

- race/runner履歴化による完全なas-of snapshot。
- odds snapshotのappend-only化。
- データ量計測後の`odds_snapshots(race_id, bet_type, fetched_at)` index。
- 必要性確認後のMCP公開。
