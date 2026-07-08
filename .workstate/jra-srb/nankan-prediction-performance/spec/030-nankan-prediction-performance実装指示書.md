# 030-nankan-prediction-performance実装指示書

## 1. 対象概要
- 対象機能:
  - 南関予想向け軽量オッズ API
  - 南関予想向け bundle API
  - bundle 専用 CLI
- 改修目的:
  - 南関予想で毎回多本数 API を叩く構成を減らし、待ち時間を短縮する
- この機能が行う処理:
  - 必要券種だけの odds を返す
  - 予想材料を 1 回の API 呼び出しで束ねる
  - CLI から bundle を 1 回で取得できるようにする
- 変更してよい範囲:
  - `src/jra_srb/models.py`
  - `src/jra_srb/app.py`
  - `src/jra_srb/cli.py`
  - `src/jra_srb/nankan_service.py`
  - `src/jra_srb/nankankeiba_pattern_service.py`
  - 新規 `src/jra_srb/nankan_prediction_service.py`
  - `tests/test_api.py`
  - `tests/test_cli.py`
  - 必要最小限の docs
- 変更してはいけない範囲:
  - 既存 `/nankan/.../odds` の契約変更
  - 既存 `call-local-api` の削除
  - pattern API / CLI の既存契約変更
  - 既存予想フローの置換までを同一タスクで始めること

## 2. 実装順序
1. `models.py` に `NankanPredictionBundle` を追加する
2. `nankan_prediction_service.py` を追加し、race_id 解決 1 回 + 並列取得の orchestration を実装する
3. `nankan_service.py` に summary 用 bet type 制限、または summary 取得 helper を追加する
4. `app.py` に `odds-summary` endpoint と `prediction-bundle` endpoint を追加する
5. `cli.py` に `fetch-nankan-prediction-bundle` subcommand を追加する
6. `tests/test_api.py` と `tests/test_cli.py` に正常系 / 異常系を追加する
7. 必要なら docs を最小更新する

## 3. 追加 / 修正対象
| 種別 | パス | 内容 |
| --- | --- | --- |
| 追加 | `src/jra_srb/nankan_prediction_service.py` | bundle orchestration |
| 修正 | `src/jra_srb/models.py` | bundle response model 追加 |
| 修正 | `src/jra_srb/nankan_service.py` | summary 対応 helper 追加 |
| 修正 | `src/jra_srb/app.py` | summary / bundle endpoint 追加 |
| 修正 | `src/jra_srb/cli.py` | bundle CLI 追加 |
| 修正 | `tests/test_api.py` | endpoint tests |
| 修正 | `tests/test_cli.py` | parser / local API 呼び出し tests |
| 任意修正 | `docs/jra/05_API仕様.md` | 新 endpoint の最小追記 |

## 4. 実装ルール
- 既存構成にない大型レイヤ分割はしない
- 新規 service は `prediction-bundle` の orchestration 責務に限定する
- 既存 `RaceOdds` は summary API で流用してよい
- `odds-summary` の既定券種は `win,wide,quinella` に固定する
- `trio` は明示指定時のみ返す
- `prediction-bundle` は部分成功レスポンスにしない
- bundle CLI は既存 `call_local_api()` を流用し、local API を 1 回だけ叩く薄い実装にする

## 5. タスク詳細
| 順序 | タスク名 | 内容 | 入力 | 出力 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | Model 追加 | `NankanPredictionBundle` を追加する | 現行 model | bundle model | nested response を型で表現できる |
| 2 | Summary 制限 | summary 許可券種と既定券種を実装する | `nankan_service.py` | summary helper | 不要券種を既定取得しない |
| 3 | Bundle service | meeting 解決、card 取得、並列 orchestration を実装する | Nankan / pattern services | bundle service | 必要要素を 1 オブジェクトで返す |
| 4 | API 追加 | 2 endpoint を追加する | `app.py` | OpenAPI 反映 | summary と bundle が GET できる |
| 5 | CLI 追加 | `fetch-nankan-prediction-bundle` を追加する | `cli.py` | 新 subcommand | local API 1 回呼び出しになる |
| 6 | Test 追加 | API / CLI tests を追加する | `tests` | テスト一式 | 正常系 / 異常系を網羅する |
| 7 | Docs 整理 | 必要なら endpoint 仕様追記 | docs | 更新 docs | 利用者向け入口が残る |

## 6. レビュー観点
- `prediction-bundle` が既存 service の寄せ集めになっているだけで、既存契約を壊していないか
- race_id 解決や card 取得の重複を増やしていないか
- `odds-summary` が本当に全券種既定取得を避けているか
- CLI が `call-local-api` の別名再実装ではなく、bundle 用の薄い入口になっているか

## 7. 禁止事項
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds` の既定挙動変更
- 既存 `fetch-nankankeiba-pattern` の置き換え
- `style-profile` や別 API の同時拡張
- 汎用 batch 機能まで同時に広げること
