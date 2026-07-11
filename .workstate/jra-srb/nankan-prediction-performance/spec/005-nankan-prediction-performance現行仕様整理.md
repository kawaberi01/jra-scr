# 005-nankan-prediction-performance現行仕様整理

## 1. 対象構成
- FastAPI 入口: [app.py](D:/develop/jra-scr/src/jra_srb/app.py)
- prediction bundle orchestration: [nankan_prediction_service.py](D:/develop/jra-scr/src/jra_srb/nankan_prediction_service.py)
- Nankan 集約 service: [nankan_service.py](D:/develop/jra-scr/src/jra_srb/nankan_service.py)
- Nankan upstream provider: [nankan_provider.py](D:/develop/jra-scr/src/jra_srb/nankan_provider.py)
- pattern service/provider:
  - [nankankeiba_pattern_service.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_service.py)
  - [nankankeiba_pattern_provider.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_provider.py)

## 2. 現行の prediction-bundle 経路
`NankanPredictionService.get_prediction_bundle()` は次の順で動く。

1. `NankanService._race_id_by_number()` で `meeting -> race_id` 解決
2. `get_race_card(race_id)` を先行取得
3. 次を `asyncio.gather()` で並列開始
   - `get_meeting_trend_context()`
   - `pattern_service.get_pattern_bundle()`
   - `get_race_odds(..., bet_types=summary_bet_types)`
   - `get_race_best_time()`
   - `get_race_closing_speed()`
   - `get_leading_jockeys()`

並列開始はしているが、各下位処理が内部で別の再取得を行うため、request 全体では重複が多い。

## 3. 観測ログで確認できた現行挙動

### 3.1 prediction-bundle の実行回数
- 同一 2R に対して `prediction-bundle` が 2 回実行されている
- API 側単体では 1 回あたり約 18 秒

### 3.2 1 回の bundle 内の主要 step
- `card`: 約 2.0 秒
- `trend_context`: 約 6.3 秒
- `pattern`: 約 4.5〜7.5 秒
- `leading_jockeys`: 約 4.8〜5.5 秒
- `best_time`: 約 9.9〜10.9 秒
- `closing_speed`: 約 11.0〜12.8 秒
- `odds_summary`: 約 13.9〜14.0 秒

### 3.3 upstream の重複
- `calendar/202607.do` を複数回取得
- `program/20260709210404.do` を複数回取得
- `uma_shosai/2026070921040402.do` を複数回取得
- `odds/202607092104040204.do` を同一 request 内で複数回取得
- pattern は `pattern_kis -> pattern_uma -> pattern_cho -> pattern_kis_cho` を順次取得

## 4. 実コード上の原因

### 4.1 card の再利用がない
[nankan_service.py](D:/develop/jra-scr/src/jra_srb/nankan_service.py) の
- `get_race_best_time()`
- `get_race_closing_speed()`
- `_complete_win_odds()`

はいずれも内部で `get_race_card()` を呼ぶ。bundle が先に card を持っていても渡していない。

### 4.2 best-time / closing-speed が meeting 補助に依存
`get_race_card()` は race card ページ取得後、天候や馬場が欠ける場合に `_meeting_conditions_for_race()` を通じて `program` を再取得する。
これにより best-time / closing-speed で card を再取得したぶんだけ `program` も再取得される。

### 4.3 odds がページ共有をしていない
`get_race_odds()` は requested bet type を順次処理する。

- `win` -> `/odds/...01.do`
- `wide` -> `/odds/...04.do`
- `quinella` -> `/odds/...04.do`

`wide` と `quinella` が同一 odds ページソースでも、現行は別 fetch になる。

### 4.4 pattern bundle は逐次取得
[nankankeiba_pattern_service.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_service.py) の `get_pattern_bundle()` は category ごとに await しており、4 ページを直列取得する。

### 4.5 trend-context は重いのに予想前に空振りしやすい
`get_meeting_trend_context()` は trend ページを取り、`race_no - 1` と比較して `usable` を決める。
今回の観測では `usable=false` かつ `reason="latest trend is post-race snapshot"` だった。
つまり 6 秒超かけて、予想に直接使えない結果を返している。

## 5. 現行仕様の整理結果
- 現行の遅延主因は `uv run` ではなく API 内部の再取得
- 並列化は入口でのみ効いており、下位の重複 I/O が支配的
- 最優先で改善すべき箇所は API service 層
- スキル側だけでは根本解決にならない
