# 020-nankan-prediction-summary-api実装計画書

## 1. 方針
- 既存 `prediction-bundle` の内部取得は再利用する。
- 返却 DTO と endpoint を追加するだけに寄せ、既存 bundle 契約は壊さない。
- trace 変更は `PredictionTraceLogger` の責務だけに閉じる。

## 2. タスク

| ID | 作業 | 対象 | 完了条件 |
| --- | --- | --- | --- |
| S01 | summary 用モデル追加 | `models.py` | API shape を型で表現できる |
| S02 | bundle -> summary 投影実装 | `nankan_prediction_service.py` | 主要指標だけを組み立てて返せる |
| S03 | endpoint 追加 | `app.py` | HTTP で summary を返せる |
| S04 | trace 追記方式へ戻す | `prediction_trace.py` | request ごとの別ファイルを作らない |
| S05 | テスト追加/修正 | `tests` | summary shape と trace 挙動を確認できる |
| S06 | API 再起動 | 運用 | 新 endpoint をローカルで確認できる |

## 3. 検証
- `tests/test_api.py`
- `tests/test_nankan_service.py`
- `tests/test_cli.py`
- 再起動後の `openapi.json` と summary endpoint 実呼び出し

## 4. リスク
- pattern 側の rate key が固定でないため、当日馬場の key 解決は欠損許容にする。
- summary 追加だけでは内部 upstream 本数は減らないため、性能改善は別タスクとして残る。
