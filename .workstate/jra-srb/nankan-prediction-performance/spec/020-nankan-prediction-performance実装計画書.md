# 020-nankan-prediction-performance実装計画書

## 1. 対象と目的
- 対象機能:
  - `odds-summary` API
  - `prediction-bundle` API
  - `fetch-nankan-prediction-bundle` CLI
- 改修目的:
  - 南関予想の 1 ターンあたり待ち時間を短縮する
- 今回の対象範囲:
  - 既存 Nankan / pattern service を再利用した軽量 summary API と bundle API の追加
  - bundle を 1 回だけ叩く CLI の追加
  - 必要最小限の response model / test 追加
- 今回やらないこと:
  - 既存予想テンプレートの全面更新
  - 汎用 batch CLI
  - 既存 endpoint の契約変更

## 2. 実装フェーズ
### Phase 1: 事前確認
- 既存 `RaceOdds` と pattern bundle 再利用可否を最終確認する
- summary 対象券種の既定値を `win,wide,quinella` に固定する

### Phase 2: 既存変更単位の特定
- `models.py` に追加が必要な model を洗い出す
- `nankan_service.py` に閉じる処理と新規 orchestration service に出す処理を分離する

### Phase 3: 対象プロジェクトの既存パターンに沿った実装
- `nankan_prediction_service.py` を追加する
- 必要なら `nankan_service.py` に summary 対応 helper を追加する

### Phase 4: 入口 / 表示 / 応答 / 設定
- `app.py` に summary endpoint / bundle endpoint を追加する
- `cli.py` に bundle CLI を追加する
- docs を最小追記する

### Phase 5: テスト
- API tests
- CLI tests
- 必要なら service 単体テスト

### Phase 6: レビュー / 完了確認
- 既存 endpoint 互換性の目視確認
- note の優先度 A/B に沿っているか確認

## 3. タスク一覧
| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | Phase 1 | summary 既定券種と bundle 含有要素を固定する | handoff note, 現行コード | 実装対象固定 | なし | `win,wide,quinella` と bundle 要素一覧が確定している |
| T02 | Phase 2 | 新規 response model / service の配置を決める | `models.py`, `app.py` | 配置方針 | T01 | `models.py` と `nankan_prediction_service.py` の責務が決まる |
| T03 | Phase 3 | summary 取得処理を実装する | `nankan_service.py` | summary 処理 | T02 | race_no ベース summary 取得ができる |
| T04 | Phase 3 | bundle orchestration service を実装する | `nankan_service.py`, `nankankeiba_pattern_service.py` | bundle service | T02 | race_id 解決 1 回 + 並列取得で bundle を返せる |
| T05 | Phase 4 | API endpoint を追加する | `app.py`, `models.py` | 新 endpoint | T03, T04 | OpenAPI に 2 endpoint が出る |
| T06 | Phase 4 | bundle CLI を追加する | `cli.py` | 新 subcommand | T05 | local API 1 回呼び出しで bundle を取得できる |
| T07 | Phase 5 | API / CLI テストを追加する | `tests/test_api.py`, `tests/test_cli.py` | 自動テスト | T05, T06 | 正常系 / 異常系が通る |
| T08 | Phase 6 | docs と最終確認を行う | 実装一式 | 完了状態 | T07 | note の A/B 方針と実装が一致している |

## 4. 完了判定
- 実装完了条件:
  - `odds-summary` endpoint が追加されている
  - `prediction-bundle` endpoint が追加されている
  - `fetch-nankan-prediction-bundle` CLI が追加されている
- テスト完了条件:
  - 対応する API / CLI テストが追加されて通る
  - 既存 `call-local-api` / pattern 関連の主要テストが落ちない
- レビュー完了条件:
  - 既存契約を壊していない
  - summary と bundle の責務が過不足なく分かれている

## 5. 別タスク候補
- `call-local-api-batch` 追加
- bundle を前提とした予想テンプレート更新
- `style-profile` 同梱検討
- bundle 内の取得時間メトリクス詳細化
