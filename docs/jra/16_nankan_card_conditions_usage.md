# 南関競馬 card API 開催条件の利用方法

## 対象 API

### race_id で取得

```http
GET /nankan/races/{race_id}/card
```

例:

```http
GET /nankan/races/2026070621040111/card?refresh=true
```

### 日付・場・レース番号で取得

```http
GET /nankan/meetings/{date_}/{course}/races/{race_no}/card
```

例:

```http
GET /nankan/meetings/2026-07-06/kawasaki/races/11/card?refresh=true
```

## 予想ロジックで見る主なフィールド

```json
{
  "race_id": "2026070621040111",
  "race_name": "アルタイル賞 Ｂ２Ｂ３ 選定馬",
  "surface": "dirt",
  "surface_label": "ダ",
  "distance": "2000",
  "start_time": "20:15",
  "weather": "rainy",
  "weather_label": "雨",
  "track_condition": "heavy",
  "track_condition_label": "重",
  "runners": [
    {
      "horse_no": "1",
      "horse_weight": "498",
      "horse_weight_diff": "-1"
    }
  ]
}
```

## 正規化ルール

### surface

- `ダ` / `ダート` -> `dirt`
- `芝` -> `turf`
- `障` / `障害` -> `obstacle`

### weather

- `晴` -> `sunny`
- `曇` -> `cloudy`
- `雨` -> `rainy`
- `小雨` -> `light_rain`
- `雪` -> `snowy`

### track_condition

- `良` -> `good`
- `稍重` -> `slightly_heavy`
- `重` -> `heavy`
- `不良` -> `bad`

## 注意点

- `weather` と `track_condition` は開催ページ `/program/{meeting_id}.do` 由来です。
- `race_id` 直接指定の card API でも、内部で `race_id` 先頭14桁の開催ページを補助取得して開催条件を埋めます。
- 古い card cache が残っている場合は `refresh=true` を付けて確認してください。
