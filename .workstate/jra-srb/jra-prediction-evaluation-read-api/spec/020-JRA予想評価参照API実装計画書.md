# 020-JRA予想評価参照API実装計画書

## 1. 対象と目的

- 対象機能: JRA予想・評価参照API
- 改修目的: SQLite直接参照なしで予想・評価を監査・検索・集計できるようにする。
- 今回の対象範囲: 詳細2本、一覧2本、集計1本のGET API、Store、Pydantic model、テスト、API仕様書。
- 今回やらないこと: DB変更、作成/評価ロジック変更、MCP公開、運用スクリプト改修。

## 2. 実装フェーズ

### Phase 1: 事前確認

- `030`と本計画を読み、`app.py`、`analysis_store.py`、`models.py`の既存差分を確認する。

### Phase 2: モデル追加

- 予想券、予想詳細、評価券結果、評価詳細、各Page、評価SummaryをPydantic modelとして追加する。

### Phase 3: Store実装

- 詳細取得、一覧取得、集計を追加し、JSON/boolを型へ復元する。
- 一覧queryは値をbindし、動的に追加するのは固定where句だけとする。

### Phase 4: API実装

- `GET /jra/evaluations/summary`を`/{evaluation_id}`より前に定義する。
- 詳細、一覧、集計routeにresponse_model、summary、query制約を付ける。

### Phase 5: テスト・文書

- Storeテスト、APIテスト、`docs/jra/05_API仕様.md`を追加・更新する。

### Phase 6: レビュー・完了確認

- 仕様突合、route順、JSON/bool変換、ページング、既存差分保持を静的確認する。

## 3. タスク一覧

| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | 事前確認 | 既存差分と対象箇所確認 | 030/020、git diff | 変更契約確認 | なし | 競合有無が判定済み |
| T02 | モデル | 参照用Pydantic model追加 | DB schema、既存Page | `models.py` | T01 | 全レスポンス項目が型定義済み |
| T03 | Store | 予想詳細・一覧追加 | T02 | Store method | T02 | JSONと券が復元される |
| T04 | Store | 評価詳細・一覧・集計追加 | T02 | Store method | T02 | bool、券、集計が復元される |
| T05 | API | GET route 5本追加 | T03/T04 | `app.py` | T03,T04 | response_modelとquery制約が設定済み |
| T06 | テスト | Store/APIテスト追加 | T03-T05 | テストコード | T05 | 仕様記載ケースを網羅 |
| T07 | 文書 | API仕様更新 | T05 | `05_API仕様.md` | T05 | endpointとfilterが記載済み |
| T08 | 確認 | 静的自己レビュー | 全変更 | review結果 | T06,T07 | 対象外混入なし |

## 4. 完了判定

- 実装完了条件: 5本のGET APIと必要なStore/modelが追加され、既存POSTの契約を変えていない。
- テスト完了条件: 必要なテストコードが追加されている。実行は人間へ引き継ぐ。
- レビュー完了条件: route競合、型変換、ページング、日付逆転、404、集計式を静的確認済み。

## 5. 別タスク候補

- 大量データ計測後の`race_id`、`theory_version`、`created_at` index追加。
- Nankanを含む共通`/analysis/predictions` APIの設計。
- 作成・評価POSTの型付きrequest/response化。
- 次順位の発走前snapshot・オッズ時系列参照API。

