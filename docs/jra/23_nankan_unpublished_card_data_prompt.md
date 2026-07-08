# 南関 card API 未発表データ判定 改修プロンプト

南関競馬の事前予想で、馬体重・増減がまだ発表されていない場合に、単なる `不足データ` ではなく、`未発表` または `取得不可` と区別して扱いたいです。

現状、`GET /nankan/meetings/{date_}/{course}/races/{race_no}/card` では、馬体重・増減が未掲載のときに各 runner の

- `horse_weight`
- `horse_weight_diff`

が `null` になります。

このままだと予想側で

- 「不足データ: 馬体重・増減」

のような曖昧な表示になり、

- upstream 側でまだ未発表なのか
- API 実装不足なのか
- 取得失敗なのか

が分かりません。

以下の方針で API と出力側を改修してください。

---

## 目的

予想時点で馬体重がまだ発表されていないケースを、実装不足や取得失敗と区別できるようにする。

---

## 改修方針

### 1. card API に未発表状態のメタ情報を追加

対象:

- `GET /nankan/races/{race_id}/card`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/card`

レスポンスに、馬体重関連の公開状態を示すメタ情報を追加してください。

候補:

```json
"data_status": {
  "horse_weight": "available"
}
```

または

```json
"data_status": {
  "horse_weight": "unpublished"
}
```

または

```json
"data_status": {
  "horse_weight": "unavailable"
}
```

### 2. `horse_weight` 状態の判定ルール

少なくとも以下を区別してください。

- `available`
  - 1頭以上で `horse_weight` または `horse_weight_diff` が取得できている
- `unpublished`
  - レース自体は取得できている
  - runner 一覧も取得できている
  - ただし全頭の `horse_weight` / `horse_weight_diff` が `null`
  - かつ upstream の出馬表上でもまだ馬体重欄が未掲載、未入力、空欄相当
- `unavailable`
  - レース取得はできたが、HTML 構造変更や想定外フォーマットで判定不能
  - あるいは馬体重欄自体の解析に失敗した

重要:

- `全頭 null` を即 `unavailable` にせず、まず `unpublished` を優先判定してください。
- 今回のような「まだ出ていない」ケースは `unpublished` に寄せたいです。

### 3. 可能なら判定理由も返す

できれば API レスポンスに簡単な理由も持たせてください。

例:

```json
"data_status": {
  "horse_weight": "unpublished",
  "horse_weight_reason": "all runners have null horse_weight before official publication"
}
```

文言は英語でも日本語でも構いませんが、呼び出し側で表示に使える程度の短さにしてください。

---

## 予想・スキル側の表示ルール

`nankan-race-predictor` などの呼び出し側では、card API の `data_status.horse_weight` を見て、以下のように表示を切り替えられるようにしてください。

### `available`

- `馬体重: yes`
- 必要なら根拠欄で増減コメントを書く

### `unpublished`

- `馬体重: 未発表`
- `不足データ` ではなく
  - `未発表データ: 馬体重・増減`
  - または `馬体重・増減は未発表`
  のように表示

### `unavailable`

- `馬体重: 取得不可`
- `不足データ` ではなく
  - `取得不可データ: 馬体重・増減`
  - または `馬体重・増減は取得不可`
  のように表示

重要:

- `未発表` と `取得不可` を混ぜないでください。
- 予想ロジック上はどちらも馬体重補正なしになりますが、ユーザー向け説明は明確に分けてください。

---

## 開催傾向 (`trend`) の扱いも合わせて整理

今回、`GET /nankan/meetings/{date_}/{course}/trend` で `race_count_completed = 12` の値が返り、1R事前予想には使えないケースがありました。

こちらは API 追加ではなく、呼び出し側ルールとして次を徹底してください。

- 対象レースが `N` R の事前予想なら
  - `trend.race_count_completed >= N`
  - または明らかに開催後データ
  の場合は当日傾向として採用しない

表示例:

- `開催傾向: 取得値が開催後時点のため今回は不採用`

---

## 期待するレスポンス例

### 馬体重未発表の例

```json
{
  "race_id": "2026070721040201",
  "track_condition": "heavy",
  "runners": [
    {
      "horse_no": "1",
      "horse_weight": null,
      "horse_weight_diff": null
    }
  ],
  "data_status": {
    "horse_weight": "unpublished",
    "horse_weight_reason": "all runners have null horse_weight before official publication"
  }
}
```

### 予想側の表示例

```text
使用データ
- 勝ちパターン分析: yes
- オッズ: yes
- 馬体重: 未発表
- 馬場状態: yes
- 当日開催傾向: no
- 未発表データ: 馬体重・増減

注意点
- 開催傾向は取得値が開催後時点だったため、1R事前予想には使わない
```

---

## 受け入れ条件

1. 馬体重未掲載レースで `data_status.horse_weight = unpublished` が返る
2. 馬体重掲載済みレースで `data_status.horse_weight = available` が返る
3. 解析失敗時だけ `unavailable` になる
4. 予想側で `未発表` と `取得不可` の表示を分けられる
5. 1R事前予想で `race_count_completed = 12` の trend は不採用にできる

---

## 補足

今回の実例では、`2026-07-07 川崎 1R` で

- card は取得できた
- odds は取得できた
- pattern は取得できた
- ただし馬体重は全頭 `null`

という状態でした。

このケースは `不足` ではなく、第一候補として `未発表` 扱いにしてください。
