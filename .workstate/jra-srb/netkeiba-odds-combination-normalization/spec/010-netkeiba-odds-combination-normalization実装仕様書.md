# netkeiba odds combination 正規化 実装仕様書

## 目的

netkeiba odds API の `combination` 絞り込みで、券種の性質に応じて順不同 / 順序ありを正しく扱う。

## 変更対象

主対象:

- `D:\develop\jra-scr\src\jra_srb\netkeiba_service.py`

テスト対象:

- `D:\develop\jra-scr\tests\test_api.py`
- または新規 `D:\develop\jra-scr\tests\test_netkeiba_service.py`

## 追加する定数

`netkeiba_service.py` に順不同券種集合を追加する。

```python
UNORDERED_NETKEIBA_BET_TYPES = {
    "bracket_quinella",
    "quinella",
    "wide",
    "trio",
}
```

順序あり券種は集合化してもよいが、必須ではない。

```python
ORDERED_NETKEIBA_BET_TYPES = {
    "exacta",
    "trifecta",
}
```

## 正規化関数

`NetkeibaService` 内の static method または module private function として、次の責務を持つ関数を追加する。

```python
def _normalize_combination(combination: list[str], ordered: bool) -> list[str]:
    ...
```

仕様:

- 各要素が数字文字列の場合は `str(int(item))` に変換する。
  - `"05"` -> `"5"`
  - `"001"` -> `"1"`
- 数字文字列でない場合は strip 済み文字列をそのまま扱う。
- `ordered=True` の場合は入力順を維持する。
- `ordered=False` の場合は正規化後の値を数値昇順で並べ替える。
- 非数字が混ざる可能性を考慮するなら、ソート key は安全にする。
  - 推奨: 数字は `(0, int(value))`、非数字は `(1, value)`。

## `_filter_odds` の変更仕様

現行:

```python
if combination:
    normalized = [str(int(item)) if item.isdigit() else item for item in combination]
    entries = [entry for entry in entries if entry.combination == normalized]
```

変更後:

1. `bet_type is None` の場合は現状通り全件返却する。
2. `entries = odds.odds.get(bet_type, [])` は現状維持する。
3. `combination` 指定時は `ordered = bet_type not in UNORDERED_NETKEIBA_BET_TYPES` として判定する。
4. query 側に `_normalize_combination(combination, ordered=ordered)` を適用する。
5. entry 側にも `_normalize_combination(entry.combination, ordered=ordered)` を適用して比較する。
6. 一致した entry は、元の `entry.combination` の順序を変更せず返す。

返却 entry の `combination` をソート済みに書き換えない。これは extractor が返した実データの表示順を維持するため。

## 券種別仕様

### 順不同

対象:

- `bracket_quinella`
- `quinella`
- `wide`
- `trio`

例:

- entry: `["13", "17"]`
- query: `["17", "13"]`
- 正規化後 entry: `["13", "17"]`
- 正規化後 query: `["13", "17"]`
- 一致

### 順序あり

対象:

- `exacta`
- `trifecta`

例:

- entry: `["17", "13", "5"]`
- query: `["17", "5", "13"]`
- 正規化後 entry: `["17", "13", "5"]`
- 正規化後 query: `["17", "5", "13"]`
- 不一致

### 単一馬

対象:

- `win`
- `place`

`ordered=True` と同じ扱いでよい。要素数が1なので順序問題は発生しない。

## 影響範囲

影響する:

- `/netkeiba/races/{race_id}/odds?bet_type=...&combination=...`
- cache hit 時の netkeiba odds 絞り込み

影響しない:

- `/netkeiba/races/{race_id}/odds` の全件返却
- `/netkeiba/races/{race_id}/result`
- 既存 JRA 公式 API
- netkeiba odds payload parser
