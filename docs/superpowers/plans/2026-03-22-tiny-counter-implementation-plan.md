# Tiny Counter Implementation Plan

## Goal

HITL フローが本当に回るかを検証するため、極小の Web アプリを独立パッケージとして追加し、短いセッション単位で進める。

## Tasks

1. tiny counter 用 progress-summary を初期化する
2. バックエンド API のテストと実装を追加する
3. HTML UI を追加する
4. 起動確認と endpoint 検証を行う
5. docs 同期の最小反映を行う

## Files

- Create: `src/hitl_tiny_counter/__init__.py`
- Create: `src/hitl_tiny_counter/app.py`
- Create: `tests/test_hitl_tiny_counter.py`
- Update: `README.md`
