# HITL Min Demo Design

## Goal

Human in the Loop で短いセッションを繰り返しながら、タスクを継続実行できることを確認する。

## Scope

- 1 つの API タスクを複数セッションで進める
- `progress-summary` から続き再開できることを確認する
- セッション終了時に次の一手が残ることを確認する

## Task

- `GET /tasks` のハンドラ追加を模したデモを行う
