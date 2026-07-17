# 000-JRAオッズsnapshot追記保存前提メモ

## 1. 対象

- 対象root: `D:\develop\jra-scr`
- 対象機能: JRAオッズsnapshot追記保存
- 改修目的: 同一レース・券種・時点ラベルの再取得でも過去snapshotを上書きせず、全世代を時系列参照可能にする。
- 関連入口: analysis collector、JRA odds timeline collector、pre-race snapshot API、odds timeline API。

## 2. 入力情報

- ユーザー要件: 共通バックログの次タスクを順次進める。
- reference_status: `not_found`
- 読み込んだreference: なし。JRA/Pythonプロジェクトに該当する同梱referenceなし。
- 参照した主要コード:
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/jra_odds_timeline.py`
  - `src/jra_srb/cli.py`
  - `tests/test_analysis_store.py`
  - `tests/test_jra_odds_timeline.py`

## 3. 成果物

- `005-JRAオッズsnapshot追記保存現行仕様整理.md`
- `010-JRAオッズsnapshot追記保存実装仕様書.md`
- `020-JRAオッズsnapshot追記保存実装計画書.md`
- `030-JRAオッズsnapshot追記保存実装指示書.md`

## 4. 注意点

- 既存DBのsnapshotとentryを失わない。
- pre-race snapshot APIの「券種ごとの最新1件」という応答形状を維持する。
- timeline collectorの既定の重複取得抑止を維持する。
