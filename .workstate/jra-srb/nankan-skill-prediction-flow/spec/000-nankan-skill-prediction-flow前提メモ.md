# 000-nankan-skill-prediction-flow前提メモ

## 目的
南関予想スキルの実行フローから、冗長な再取得、不要なファイル保存、中間 JSON の過剰展開を減らす。

## 対象
- `C:\Users\main\skills\nankan-race-predictor\SKILL.md`
- `C:\Users\main\skills\nankan-race-session-starter\SKILL.md`

## 背景
- API 観測ログでは、同一レースで `prediction-bundle` が 2 回実行されていた。
- 実行途中メッセージでは、`prediction-bundle` を一旦ファイル保存し、保存失敗・文字コード・JSON 形状確認の切り分けが追加発生していた。
- その後、買い目具体化のために `quinella` 個別取得が複数本走っていた。

## 今回の整理対象
- スキル文面に残っている「bundle 優先だが再取得もあり得る」曖昧さ
- bundle 成功後の個別 API 追加取得条件の曖昧さ
- 標準運用でのファイル保存や ad hoc 解析の混入
- 通常予想と観測実行のモード境界の曖昧さ

## 対象外
- `jra-srb` API 本体の最適化
- モデル自体の reasoning 設定変更
- 予想ロジックの評価軸そのものの見直し
