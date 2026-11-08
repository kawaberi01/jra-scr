---
name: nankan-result-save-to-analysis-sqlite
description: 南関競馬の確定結果をローカル API から取得し、analysis.sqlite の race_results / result_entries / payouts に保存して検証するスキル。川崎・浦和・船橋・大井の単発結果保存や、予想検証前の DB 反映に使う。
---

# Nankan Result Save To Analysis SQLite

南関競馬の 1 レース分の確定結果を、`analysis.sqlite` へ保存するための skill です。

結果 API を使う前に [local-race-api-ready](../local-race-api-ready/SKILL.md) を実行する。同じ作業で準備済みなら再実行せず、失敗したら結果取得・保存に進まない。

## 目的

- ローカル API から南関の結果と払戻を取得する
- `analysis.sqlite` の次の 3 テーブルへ保存する
  - `race_results`
  - `result_entries`
  - `payouts`
- 保存後に件数確認まで行う

## 入力

- `date`
  - `YYYY-MM-DD`
- `course`
  - `kawasaki` / `urawa` / `funabashi` / `ohi`
- `race_no`
  - 数値
- 任意: `db`
  - 既定は `D:\develop\jra-scr\data\db\analysis.sqlite`
- 任意: `base_url`
  - 既定は `http://127.0.0.1:8000`

## 実行方針

1. 対象レースを 1 件に固定する。
2. `uv run jra-srb call-local-api "/nankan/meetings/{date}/{course}/races/{race_no}/result"` で結果 JSON を取得する。
3. 取得 JSON の `race_id`、`race_name`、`results`、`payouts` を確認する。
4. `scripts/save_nankan_result_to_analysis_sqlite.py` を `uv run python` で実行する。
5. 保存後に `race_results`、`result_entries`、`payouts` の件数を確認する。
6. 最後に、対象 `race_id`、保存件数、未確認事項を短く報告する。

## 保存ルール

- `race_results`
  - `race_id` 単位で upsert する
- `result_entries`
  - 対象 `race_id` の既存行を削除してから再挿入する
- `payouts`
  - 対象 `race_id` の既存行を削除してから再挿入する
- `payout` と `popularity` は整数化して保存する
- 文字列の券種は API の値をそのまま使う

## 実行コマンド

```powershell
uv run python "C:\Users\main\skills\nankan-result-save-to-analysis-sqlite\scripts\save_nankan_result_to_analysis_sqlite.py" --date 2026-07-09 --course kawasaki --race 1
```

DB パスを変える場合:

```powershell
uv run python "C:\Users\main\skills\nankan-result-save-to-analysis-sqlite\scripts\save_nankan_result_to_analysis_sqlite.py" --date 2026-07-09 --course kawasaki --race 1 --db "D:\develop\jra-scr\data\db\analysis.sqlite"
```

## 確認方法

保存後に少なくとも次を確認する。

- `race_results = 1`
- `result_entries = 着順件数`
- `payouts = 払戻件数`

スクリプトは確認結果を標準出力へ出す。

## 注意

- API 取得自体が成功しても、DB 側の保存件数を見ずに完了扱いしない
- `stored/results` API ではなく、`analysis.sqlite` の実テーブルを正として確認する
- 複数レースまとめ保存には使わない。1 レースずつ実行する
- API サーバー `http://127.0.0.1:8000` の準備確認に成功してから取得する
