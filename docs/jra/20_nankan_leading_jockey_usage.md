# 南関リーディングジョッキー API 利用方法

## API

```http
GET /nankan/leading/jockeys
```

## クエリ

- `course`: `urawa`, `funabashi`, `ohi`, `kawasaki`
- `distance`: `800`, `900`, `1000`, `1200`, `1300`, `1400`, `1500`, `1600`, `1650`, `1700`, `1800`, `1900`, `2000`, `2100`, `2200`, `2400`, `2600`
- `track_condition`: `good`, `slightly_heavy`, `heavy`, `bad`
- `period`: `recent_3months`, `recent_1year`, または `2026` のような年
- `sort`: `wins`, `earnings`, `win_rate`, `quinella_rate`
- `refresh`: `true` でキャッシュを使わず再取得

## 例

```bash
curl "http://127.0.0.1:8000/nankan/leading/jockeys?course=kawasaki&distance=1400&track_condition=good&period=recent_3months&sort=win_rate"
```

## レスポンス

```json
{
  "source": "nankankeiba",
  "source_url": "https://www.nankankeiba.com/leading_kis/211400010004031.do",
  "requested_condition_code": "211400010004031",
  "effective_condition_code": "211400010004031",
  "fallback": false,
  "course": "kawasaki",
  "distance": 1400,
  "track_condition": "good",
  "period": "recent_3months",
  "sort": "win_rate",
  "generated_at": "2026-07-07T10:00:00Z",
  "items": [
    {
      "rank": 1,
      "jockey_code": "12345",
      "jockey_name": "野畑凌",
      "rides": 120,
      "wins": 24,
      "seconds": 18,
      "thirds": 11,
      "win_rate": 20.0,
      "quinella_rate": 35.0,
      "trio_rate": 44.2
    }
  ],
  "cache_hit": false
}
```

## 予想での扱い

リーディングジョッキーは補正材料です。勝ちパターン分析、オッズ、馬場状態、馬体重を主材料にし、短距離戦や接戦時の順位補正、相手候補の取捨に使います。

リーディングジョッキーだけで本命を決めないでください。`pattern_kis` や `pattern_kis_cho` と同方向の場合は加点を強め、馬の場・距離率が弱い場合は騎手成績だけで頭固定しない運用にします。

## 注意

公式ページ側の条件URLが未集計または存在しない場合は、ベースページへフォールバックします。その場合は `fallback: true`、`requested_condition_code` に要求した条件コード、`effective_condition_code` に実際に取得した条件コードを返します。ランキング表が見つからない場合はエラーではなく `items: []` を返します。
