# 次に有益な改修候補 前提メモ

作成日: 2026-06-28

## 目的

README 整備後に、次へ進めると効果が大きい改修候補を整理し、実装に渡せる粒度のタスクへ分解する。

## 対象

- Project: `jra-srb`
- Feature: `next-beneficial-improvements`
- 対象 root: `D:\develop\jra-scr`

## 今回は対象外

- 実装変更
- テスト実行
- 外部 JRA サイトへの疎通確認
- 大規模な設計刷新

## 調査根拠

- `README.md`
- `docs/jra/07_現在地と次の一手.md`
- `docs/jra/08_実装タスクと優先順位.md`
- `src/jra_srb/app.py`
- `src/jra_srb/service.py`
- `src/jra_srb/provider.py`
- `src/jra_srb/batch.py`
- `tests/test_api.py`
- `tests/test_provider.py`
- `tests/test_batch.py`

## 判断方針

優先度は、次の順で評価した。

1. 既存 API / MCP を利用者が実用しやすくなるか
2. 運用時の失敗調査や再実行が楽になるか
3. 既存実装の延長で小さく実装できるか
4. テストで完了条件を固定しやすいか
