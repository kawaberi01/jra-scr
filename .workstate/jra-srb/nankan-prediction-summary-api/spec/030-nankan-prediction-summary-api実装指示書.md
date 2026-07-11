# 030-nankan-prediction-summary-api実装指示書

## 1. 目的
`prediction-bundle` の全量 DTO を会話へ流さずに済むよう、AI 予想用の軽量 summary endpoint を追加する。

## 2. 変更してよい範囲
- [src/jra_srb/models.py](D:/develop/jra-scr/src/jra_srb/models.py)
- [src/jra_srb/nankan_prediction_service.py](D:/develop/jra-scr/src/jra_srb/nankan_prediction_service.py)
- [src/jra_srb/app.py](D:/develop/jra-scr/src/jra_srb/app.py)
- [src/jra_srb/prediction_trace.py](D:/develop/jra-scr/src/jra_srb/prediction_trace.py)
- [tests/test_api.py](D:/develop/jra-scr/tests/test_api.py)
- [tests/test_nankan_service.py](D:/develop/jra-scr/tests/test_nankan_service.py)
- [tests/test_cli.py](D:/develop/jra-scr/tests/test_cli.py)

## 3. 変更してはいけない範囲
- 既存 `/prediction-bundle` のレスポンス shape
- 既存 CLI 契約
- 予想ロジック本体
- DB スキーマ

## 4. 実装順序
1. summary DTO を `models.py` に追加する。
2. `NankanPredictionService` に `get_prediction_summary()` を追加する。
3. bundle から runner ごとの主要指標を投影する helper を service 内に追加する。
4. `app.py` に `/prediction-summary` endpoint を追加する。
5. `PredictionTraceLogger` を 1 ファイル追記へ戻す。
6. service/API/trace テストを追加または更新する。

## 5. テスト観点
- summary endpoint が `meeting_no` / `meeting_day` 必須であること
- summary endpoint が race 基本情報と runner 一覧を返すこと
- runner に best_time / closing_speed / pattern / 単勝人気が投影されること
- trace logger が `request_trace_id` 付きでもベースファイルへ追記すること

## 6. 人手確認観点
- `/openapi.json` に `prediction-summary` が出ること
- `/prediction-summary` 実呼び出しで bundle より小さい JSON になっていること
- `JRA_SRB_PREDICTION_TRACE_PATH` のファイルへ追記されること

## 7. 禁止事項
- summary 実装のために別の永続化層や generic mapper を新設しない
- summary を bundle 文字列加工で作らない
- ここで skill 側プロンプト改修まで混ぜない

## 8. 停止条件
- summary に何を残すかで既存運用と衝突する場合
- 既存 bundle 契約を壊さないと実装できない場合
