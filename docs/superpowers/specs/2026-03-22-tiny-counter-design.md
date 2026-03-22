# Tiny Counter Design

## Goal

Human in the Loop フローを検証するための極小 Web アプリとして、1 画面のカウンターアプリを作る。

## Scope

- 現在値を表示する
- ボタンで値を 1 増やす
- ボタンで 0 に戻す

## Architecture

- FastAPI の独立アプリとして `src/` 配下に追加する
- 状態はメモリ上の整数 1 個だけを持つ
- 画面は HTML を直接返す
- 更新は JSON API を使う

## Endpoints

- `GET /`:
  - 画面
- `GET /api/value`:
  - 現在値取得
- `POST /api/increment`:
  - 値を 1 増やす
- `POST /api/reset`:
  - 値を 0 に戻す

## Notes

- 永続化はしない
- 認証はない
- docs 同期の最小例も確認する
