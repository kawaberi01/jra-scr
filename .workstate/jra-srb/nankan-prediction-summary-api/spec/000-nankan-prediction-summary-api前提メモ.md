# 000-nankan-prediction-summary-api前提メモ

## 1. 背景
- スキル実行中に `prediction-bundle` 全量 JSON を会話へ持ち込むと、レスポンス本文そのものが大きく、以後の推論トークン消費が増える。
- データ取得元を API -> DB に変えても、返却 DTO が全量のままならトークン削減効果は限定的である。
- 必要なのは取得経路の変更ではなく、API 側で「予想に使う主要指標だけへ投影した軽量レスポンス」を返すこと。

## 2. 今回の目的
- `prediction-bundle` とは別に、AI 予想用の軽量レスポンスを返す API を追加する。
- スキル側が長文説明や中間 JSON 抽出を行わなくても、主要比較材料をそのまま読める形にする。
- 既存の観測ログは維持しつつ、trace 出力は request ごとの別ファイル分割ではなく 1 ファイル追記へ戻す。

## 3. 対象
- [src/jra_srb/models.py](D:/develop/jra-scr/src/jra_srb/models.py)
- [src/jra_srb/nankan_prediction_service.py](D:/develop/jra-scr/src/jra_srb/nankan_prediction_service.py)
- [src/jra_srb/app.py](D:/develop/jra-scr/src/jra_srb/app.py)
- [src/jra_srb/prediction_trace.py](D:/develop/jra-scr/src/jra_srb/prediction_trace.py)
- [tests/test_api.py](D:/develop/jra-scr/tests/test_api.py)
- [tests/test_nankan_service.py](D:/develop/jra-scr/tests/test_nankan_service.py)
- [tests/test_cli.py](D:/develop/jra-scr/tests/test_cli.py)

## 4. 非対象
- 予想ロジックそのものの変更
- skill 側の最終プロンプト組み立て変更
- `prediction-bundle` 内部の upstream 呼び出し削減
- DB 保存構造の変更

## 5. 確認方法
- API テストで summary endpoint の shape を確認する。
- service テストで主要 runner 指標が投影されることを確認する。
- trace logger テストでベースファイルへ追記されることを確認する。
