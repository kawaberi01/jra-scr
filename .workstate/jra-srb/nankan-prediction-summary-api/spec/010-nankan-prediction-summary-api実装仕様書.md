# 010-nankan-prediction-summary-api実装仕様書

## 1. 目的
AI がそのまま読める軽量な予想用レスポンスを API 側で返し、会話上の JSON 展開量を減らす。

## 2. 追加 API
- Path:
  - `/nankan/meetings/{date_}/{course}/races/{race_no}/prediction-summary`
- Query:
  - `meeting_no` 必須
  - `meeting_day` 必須
  - `bet_types` 任意
  - `refresh` 任意

## 3. 返却モデル
`NankanPredictionSummary` を追加し、以下を返す。

### 3.1 race レベル
- `race_id`
- `date`
- `course`
- `race_no`
- `meeting_no`
- `meeting_day`
- `distance`
- `track_condition`
- `track_condition_label`
- `data_status`
- `trend`
- `leading_jockeys`
- `runners`
- `meta`

### 3.2 trend
- `usable`
- `reason`
- `race_count_completed`
- `required_max_completed`
- `frame_top3`
- `jockey_top3`
- `trainer_top3`

各 top3 は件数上位 3 件までに絞る。

### 3.3 leading_jockeys
- `course`
- `distance`
- `track_condition`
- `period`
- `sort`
- `items`

`items` は rank, jockey_name, win_rate, quinella_rate, trio_rate のみ。

### 3.4 runner
- 枠番, 馬番, 馬名, 性齢, 斤量, 騎手, 調教師
- 馬体重, 馬体重増減
- 単勝オッズ, 人気
- best time: 値, 順位, 同コース, 同距離, 馬場
- closing speed: 値, 順位, 同コース, 同距離, 馬場
- pattern:
  - `pattern_uma.rates["course"]`
  - `pattern_uma.rates["distance"]`
  - `pattern_uma.track_condition_rates[当日馬場]`
  - `pattern_kis.jockey_riding_rate`
  - `pattern_kis_cho.rates[course]`

## 4. 投影ルール
- 元データは `get_prediction_bundle()` をそのまま利用する。
- `fetched_at`, `source`, `meta` など AI 予想で不要な詳細は summary から落とす。
- `track_condition` のキー解決は card の当日馬場文字列を正規化せず、そのまま pattern 側辞書の一致キーで引く。見つからない場合は `None`。
- runner は race card の並び順を維持する。

## 5. trace 仕様
- `PredictionTraceLogger` は常に環境変数で指定されたベースファイルへ追記する。
- `request_trace_id` はレコード内フィールドとして残すが、出力ファイル名には使わない。

## 6. 成功条件
- summary endpoint が full bundle より明らかに小さい shape を返す。
- 主要指標が API 側で整形され、スキル側の追加抽出が不要になる。
- trace が 1 ファイル追記へ戻る。
