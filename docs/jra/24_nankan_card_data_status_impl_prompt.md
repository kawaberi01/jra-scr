# 南関 card API `data_status.horse_weight` 実装指示プロンプト

`docs/jra/05_API仕様.md` に追記した `data_status.horse_weight` 仕様が、実レスポンスにまだ反映されていません。

現状確認:

- `GET /nankan/meetings/2026-07-07/kawasaki/races/1/card`
- `GET /nankan/races/{race_id}/card`

で、`horse_weight` / `horse_weight_diff` は全頭 `null` になりますが、レスポンスに

```json
"data_status": {
  "horse_weight": "unpublished"
}
```

のような情報がまだ出ていません。

仕様書だけでなく、API 実装とレスポンスモデルまで反映してください。

---

## 目的

馬体重・増減が

- 取得できたのか
- まだ未発表なのか
- 取得失敗なのか

を API レスポンスで区別できるようにする。

---

## 対象 API

- `GET /nankan/races/{race_id}/card`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/card`

---

## 実装要件

### 1. card レスポンスに `data_status` を追加

card API のレスポンスに、少なくとも以下を追加してください。

```json
"data_status": {
  "horse_weight": "available"
}
```

`horse_weight` の値は次のいずれかです。

- `available`
- `unpublished`
- `unavailable`

可能なら理由も返してください。

例:

```json
"data_status": {
  "horse_weight": "unpublished",
  "horse_weight_reason": "all runners have null horse_weight before official publication"
}
```

---

### 2. 判定ルール

#### `available`

次のいずれかを満たす場合:

- 1頭以上で `horse_weight` が非 null
- 1頭以上で `horse_weight_diff` が非 null

#### `unpublished`

次をすべて満たす場合:

- race card 自体は取得できている
- runners 一覧も取得できている
- 全頭の `horse_weight` / `horse_weight_diff` が `null`
- upstream 上で馬体重欄が未発表、空欄、未入力相当

重要:

- `全頭 null` をそのまま `unavailable` にしないでください
- 今回のような「開催前でまだ馬体重未発表」のケースは `unpublished` を優先してください

#### `unavailable`

次のような場合:

- HTML 構造変更で馬体重欄の解析に失敗
- runners は取れたが馬体重欄の有無や状態の判定が壊れている
- 想定外形式で、未発表か取得失敗かを安全に判定できない

---

### 3. レスポンスモデルも更新

Pydantic モデルや OpenAPI スキーマにも `data_status` を追加してください。

期待イメージ:

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

---

### 4. 既存レスポンスとの互換

- 既存の `runners[].horse_weight`
- 既存の `runners[].horse_weight_diff`

はそのまま維持してください。

今回は追加のみで、既存フィールドの意味変更はしないでください。

---

## 実装候補箇所

想定箇所:

- `src/jra_srb/models.py`
  - card レスポンスモデルに `data_status` を追加
- `src/jra_srb/nankan_extractors.py`
  - 馬体重欄の状態判定ロジック追加
- `src/jra_srb/nankan_service.py`
  - card 組み立て時に `data_status` を詰める
- `src/jra_srb/app.py`
  - OpenAPI へ反映されるモデル定義確認

構成が違う場合は既存実装に合わせて調整してください。

---

## テスト要件

少なくとも次を追加してください。

### ケース1: 馬体重あり

- 一部または全頭に `horse_weight` がある fixture
- `data_status.horse_weight == "available"`

### ケース2: 馬体重未発表

- 全頭 `horse_weight == null`
- 全頭 `horse_weight_diff == null`
- `data_status.horse_weight == "unpublished"`

今回の `2026-07-07 川崎 1R` 相当がこの扱いです。

### ケース3: 解析失敗

- 想定外 HTML または判定不能 fixture
- `data_status.horse_weight == "unavailable"`

可能なら API レベルテストでも確認してください。

---

## 受け入れ条件

1. `/nankan/.../card` レスポンスに `data_status.horse_weight` が出る
2. 全頭 `null` かつ未発表相当ケースで `unpublished` が返る
3. 馬体重ありケースで `available` が返る
4. 解析失敗時だけ `unavailable` が返る
5. `openapi.json` にも `data_status` が反映される

---

## 補足

予想スキル側ではすでに次の扱いに寄せています。

- `available` -> `馬体重: yes`
- `unpublished` -> `馬体重: 未発表`
- `unavailable` -> `馬体重: 取得不可`

そのため、API がこの契約を返せば、予想側の表示も安定します。
