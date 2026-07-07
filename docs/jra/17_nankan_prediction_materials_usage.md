# 南関競馬 予想材料 API 利用方法

## 目的

南関競馬の予想ロジックで、以下の材料を組み合わせて使うための API 利用手順です。

- 勝ちパターン分析
- オッズ
- 馬体重
- 馬場状態
- 当日開催傾向
- 持ち時計
- 上がり時計
- 脚質傾向

## 基本指定

日付・場・レース番号で取得する場合:

```http
GET /nankan/meetings/{date_}/{course}/races/{race_no}/{resource}
```

race_id で取得する場合:

```http
GET /nankan/races/{race_id}/{resource}
```

例:

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/best-time
GET /nankan/races/2026070621040101/best-time
```

`refresh=true` を付けるとキャッシュを避けて再取得します。

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/best-time?refresh=true
```

## 推奨取得順

1. 出馬表
2. オッズ
3. 当日開催傾向
4. 持ち時計
5. 上がり時計
6. 脚質傾向
7. 勝ちパターン分析

出馬表には馬体重、馬場状態、距離、発走時刻が含まれます。脚質傾向は各馬ページを辿るため、他の補助 API より取得コストが高めです。

## 出馬表・馬場状態

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/card
```

主に使う項目:

- `race_name`
- `course`
- `surface`
- `distance`
- `start_time`
- `weather`
- `track_condition`
- `runners[].horse_weight`
- `runners[].horse_weight_diff`

## 当日開催傾向

```http
GET /nankan/meetings/2026-07-06/kawasaki/trend
```

主に使う項目:

- `race_count_completed`
- `summary.frame`
- `summary.running_style.front_group_top3_count`
- `summary.running_style.back_group_top3_count`
- `summary.jockey`
- `summary.trainer`
- `summary.payout`

集計前または未公開の場合は 404 ではなく、`race_count_completed: 0` と空の `summary` が返ります。

## 持ち時計

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/best-time
```

用途:

- 同条件での持ち時計比較
- ベース能力比較
- 人気薄の能力裏付け

主に使う項目:

- `runners[].horse_no`
- `runners[].horse_name`
- `runners[].best_time`
- `runners[].best_time_rank`
- `runners[].best_time_source_course`
- `runners[].best_time_source_distance`
- `runners[].same_course_flag`
- `runners[].same_distance_flag`
- `runners[].track_condition`

注意:

南関公式の持ち時計ページには source race_id / source date が表示されないため、`best_time_source_race_id` と `best_time_source_date` は `null` になる場合があります。

## 上がり時計

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/closing-speed
```

用途:

- 終い性能比較
- 差し脚確認
- 脚質推定の補助

主に使う項目:

- `runners[].horse_no`
- `runners[].horse_name`
- `runners[].best_closing_time`
- `runners[].best_closing_rank`
- `runners[].same_course_flag`
- `runners[].same_distance_flag`
- `runners[].track_condition`
- `runners[].closing_section_distance`

`closing_section_distance` は 3F として `600` を返します。

注意:

南関公式の上がり時計ページには source race_id / source date が表示されないため、`closing_time_source_race_id` と `closing_time_source_date` は `null` になる場合があります。

## 脚質傾向

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/style-profile
```

用途:

- 当日開催傾向の「前有利」「後方不利」を各馬に接続する
- 固定ラベルではなく、近走ベースのスコアとして扱う

主に使う項目:

- `runners[].style_scores.front`
- `runners[].style_scores.stalker`
- `runners[].style_scores.midpack`
- `runners[].style_scores.closer`
- `runners[].expected_style`
- `runners[].sample_size`
- `runners[].recent_races[].corner_positions`
- `runners[].recent_races[].field_size`
- `runners[].recent_races[].distance`
- `runners[].recent_races[].track_condition`
- `runners[].recent_races[].finish_rank`

推定ルール:

- 各馬ページの近走成績から `コーナー 通過順` を最大5走取得します。
- 通過順平均を頭数比に正規化します。
- 前から 25% 以内を `front`、45% 以内を `stalker`、70% 以内を `midpack`、それ以降を `closer` として集計します。
- 最も高いスコアを `expected_style` にします。
- サンプルがない場合は `sample_size: 0`、`expected_style: null` になります。

## 勝ちパターン分析

```http
GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1
```

主に使う項目:

- `runners[].categories`
- 騎手、馬場、季節、枠などのカテゴリ別成績

## 予想ロジックでの使い分け

- 持ち時計: ベース能力
- 上がり時計: 終い性能
- 脚質傾向: 当日開催傾向との接続
- 当日開催傾向: 補正材料
- オッズ: 市場評価と妙味
- 馬体重: 当日状態
- 馬場状態: 条件補正
- 勝ちパターン分析: 条件適性の裏付け

## 最小取得例

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/1/card
GET /nankan/meetings/2026-07-06/kawasaki/races/1/odds
GET /nankan/meetings/2026-07-06/kawasaki/trend
GET /nankan/meetings/2026-07-06/kawasaki/races/1/best-time
GET /nankan/meetings/2026-07-06/kawasaki/races/1/closing-speed
GET /nankan/meetings/2026-07-06/kawasaki/races/1/style-profile
GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1
```

