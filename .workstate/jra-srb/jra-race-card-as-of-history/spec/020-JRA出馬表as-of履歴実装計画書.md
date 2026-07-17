# 020-JRA出馬表as-of履歴実装計画書

## 1. 対象と目的

- 対象機能: JRA-NEXT-003 出馬表のas-of履歴化
- 目的: 発走前cardとオッズを指定観測時点で再現する。
- 対象: model、extractor、service、SQLite Store、定刻collector、snapshot API、文書、pytest。
- 対象外: 過去履歴backfill、結果由来補完、性能index、MCP。

## 2. 実装フェーズ

### Phase 1: model・抽出契約

- card品質、source種別、runner状態をadditive fieldとして追加する。
- JRA parserで完全性と明示取消を判定する。

### Phase 2: 永続化

- card snapshot親子tableを追加する。
- 最新値tableへadditive migrationを行う。
- `write_card()`をappend履歴と互換最新値の同一transactionへ変更する。

### Phase 3: as-of参照

- Storeへtimezone付き`as_of`を追加する。
- cardとoddsの両方へ境界を適用する。
- 旧DB fallbackと結果リーク防止を維持する。

### Phase 4: 定刻収集

- serviceのcard cacheを明示的にbypass可能にする。
- オッズ観測taskごとにcardを1回保存する。

### Phase 5: テスト・文書

- extractor、Store、API、collectorテストを追加・更新する。
- API仕様を更新する。
- 対象テスト、全pytest、ruff、compile確認、diff checkを実行する。

## 3. タスク一覧

| ID | 作業内容 | 主な対象 | 依存 | DoD |
| --- | --- | --- | --- | --- |
| M01 | card品質・runner状態model追加 | `models.py` | なし | additive fieldが型付け済み |
| E01 | JRA完全性・明示取消抽出 | `extractors.py` | M01 | 通常/取消/不完全test成功 |
| S01 | card refresh対応 | `service.py` | E01 | cache bypass可能 |
| D01 | 履歴schema・migration | `analysis_store.py` | M01 | 旧行を保持しtable/column追加 |
| D02 | append保存・取消導出・最新同期 | `analysis_store.py` | D01 | 完全/不完全/result契約一致 |
| A01 | as-of card/odds合成 | `analysis_store.py`, `app.py` | D02 | 境界以前だけを返す |
| C01 | 定刻card収集 | `jra_odds_timeline.py` | S01,D02 | taskごとにcard世代保存 |
| T01 | 自動テスト | tests | 全実装 | 010の主要契約を網羅 |
| DOC01 | API・progress更新 | docs, `.workstate` | T01 | 利用/再開情報が最新 |
| V01 | 検証 | repository | T01 | pytest/ruff/compile/diff成功 |

## 4. 完了判定

- 指定時点のrace、runner、取消、騎手、馬体重、オッズを再現できる。
- 不完全cardと結果pageがas-of候補にならない。
- `as_of`省略時と旧DB互換が維持される。
- 対象テストと全テスト、ruff、compile確認が成功する。

## 5. 別タスク候補

- 実データ件数に基づく履歴query index追加は`JRA-NEXT-016`。
- 未知のJRA取消markup対応はfixture入手時に追加する。
