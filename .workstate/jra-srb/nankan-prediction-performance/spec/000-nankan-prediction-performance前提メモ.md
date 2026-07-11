# 000-nankan-prediction-performance前提メモ

## 1. 対象
- 対象 root: `D:\develop\jra-scr`
- 対象プロジェクト: `jra-srb`
- 対象機能: 南関予想用 `prediction-bundle` の API 側遅延改善
- 目的:
  - 予想 1 回あたりの API 側待ち時間を下げる
  - 同一 request 内の重複取得を減らす
  - スキル側変更の前に API 側の根本ボトルネックを除去する

## 2. 今回の判断材料
- 観測ログ:
  - [prediction_trace_20260709_kawasaki_1r.jsonl](D:/develop/jra-scr/.workstate/logs/prediction_trace_20260709_kawasaki_1r.jsonl)
- 補助メモ:
  - [2026-07-08_prediction_performance_handoff.md](D:/develop/jra-scr/notes/2026-07-08_prediction_performance_handoff.md)
- 主な参照コード:
  - [app.py](D:/develop/jra-scr/src/jra_srb/app.py)
  - [nankan_prediction_service.py](D:/develop/jra-scr/src/jra_srb/nankan_prediction_service.py)
  - [nankan_service.py](D:/develop/jra-scr/src/jra_srb/nankan_service.py)
  - [nankan_provider.py](D:/develop/jra-scr/src/jra_srb/nankan_provider.py)
  - [nankankeiba_pattern_service.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_service.py)
  - [nankankeiba_pattern_provider.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_provider.py)

## 3. 観測で確定した事実
- 対象 request:
  - `GET /nankan/meetings/2026-07-09/kawasaki/races/2/prediction-bundle?meeting_no=4&meeting_day=4&refresh=true`
- 同一レースで `prediction-bundle` が 2 回実行されていた
  - 1 回目: 約 17.6 秒
  - 2 回目: 約 18.6 秒
- 1 回の bundle 内でも重い step がある
  - `odds_summary`: 約 14.0 秒
  - `closing_speed`: 約 11.0 秒〜12.8 秒
  - `best_time`: 約 9.9 秒〜10.9 秒
  - `pattern`: 約 4.5 秒〜7.5 秒
  - `trend_context`: 約 6.3 秒
- `refresh=true` により cache を使い切らず、外部再取得寄りの挙動になる
- 予想後に個別 odds API が 4 本追加で呼ばれ、それぞれ 8〜11 秒かかっている

## 4. API 側の主要問題
1. `prediction-bundle` 内で同一 request の補助データを使い回していない
2. `best_time` / `closing_speed` が内部で再度 `get_race_card()` を呼ぶ
3. `get_race_card()` が meeting 条件補完のために `program` を追加取得する
4. `get_race_odds()` が bet_type ごとに逐次 fetch し、同一 odds ページを再取得する
5. pattern bundle が category ごとに逐次 fetch する
6. `trend_context` が重い一方で、予想時点では `usable=false` となるケースがある

## 5. 今回の仕様化で扱う範囲
- API 側の service / provider / endpoint の改善仕様までを定義する
- スキル / テンプレート / 会話側プロンプトの変更仕様は含めない
- 既存 API 契約は可能な限り維持し、内部実装の重複削減を優先する

## 6. 注意点
- `prediction-bundle` endpoint 自体は残す
- 既存 `/nankan/.../odds` 契約は壊さない
- 既存 cache の意味は維持する
- 可観測性として今回追加した prediction trace は残し、改善後比較に使う
