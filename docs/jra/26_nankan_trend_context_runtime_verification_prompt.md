# 南関 trend-context 開催中検証プロンプト

## 目的

`GET /nankan/meetings/{date}/{course}/races/{race_no}/trend-context` が、
開催中の時点で期待どおりの `race_count_completed` を返しているかを切り分ける。

確認したい論点は次の3つです。

1. API が本当に当日の live trend を見ているか
2. `refresh=false` と `refresh=true` で値が変わるか
3. `race_count_completed` が対象レース時点を超えているなら、それは live 値か cache 値か

---

## 実行タイミング

- なるべく `8R` の発走前に実行する
- できれば `7R 結果反映後` から `8R 発走前` の間に実行する
- 同じ内容を 2 回から 3 回、数分おきに繰り返す

---

## Codex への実行プロンプト

以下をそのまま渡してください。

```text
南関の開催中 trend-context の実挙動を検証してください。
対象は本日の川崎 8R です。

目的は、trend-context がその時点の当日傾向を返しているか、
それとも future snapshot / cache / 別データを見ているかを切り分けることです。

必ず API のみを使ってください。推測で補わず、取得した値をそのまま整理してください。

確認手順:
1. `/nankan/meetings/2026-07-08/kawasaki/races/8/trend-context`
   を `refresh=false` 相当で 1 回取得
2. 同じ endpoint を `refresh=true` で 1 回取得
3. 可能なら 30秒から60秒後に `refresh=true` で再取得
4. あわせて `/nankan/meetings/2026-07-08/kawasaki/trend?refresh=true`
   も取得して比較
5. 可能なら `/nankan/meetings/2026-07-08/kawasaki/races/7/result`
   の取得可否も確認し、7R が結果確定済みかを添える

各レスポンスについて必ず次を出してください。
- 取得時刻
- endpoint
- refresh の有無
- source
- fetched_at
- race_count_completed
- required_max_completed
- usable
- reason
- summary が空かどうか

比較観点:
- refresh=false と refresh=true で差があるか
- trend と trend-context で race_count_completed が同じか
- 8R事前時点なのに race_count_completed が 8 以上になっていないか
- 7R結果取得状況と trend の completed 件数が整合しているか

出力ルール:
- 事実と推測を分ける
- 最後に「API側の問題」「呼び出し側の問題」「要追加観測」の3分類で短く結論を書く
- もし completed 件数が不自然なら、次に API に追加すべき観測項目も書く
```

---

## 期待する見方

### 正常寄り

- `8R` 事前なら `required_max_completed = 7`
- `race_count_completed` は `0` から `7` の範囲
- `usable = true`

### 不自然

- `race_count_completed >= 8`
- `refresh=false` と `refresh=true` で大きく差がある
- `trend-context` と `trend` の `race_count_completed` が不整合
- `7R result` 未確定なのに `race_count_completed = 7` 以上

---

## 追加で確認できるとよいこと

もし API 側に観測項目を追加できるなら、`trend-context` に次を出すと切り分けが早いです。

- `cache_hit`
- `cache_expires_at`
- `cache_key`
- `upstream_fetched_at`
- `raw_race_count_completed_text`

これがあれば、
「live を見たのか」「古い cache を見たのか」「HTML 解析がずれたのか」
を切り分けやすくなります。
