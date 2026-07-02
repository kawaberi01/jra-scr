# netkeiba odds combination 正規化 現行仕様整理

## API 入口

FastAPI ルート:

- `D:\develop\jra-scr\src\jra_srb\app.py`
- 関数: `get_netkeiba_race_odds`

query parameter:

- `bet_type: str | None`
- `combination: str | None`
- `refresh: bool`

`combination` は API 層でカンマ区切りから `list[str]` に変換される。

```python
parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
```

## Service 処理

対象:

- `D:\develop\jra-scr\src\jra_srb\netkeiba_service.py`
- class: `NetkeibaService`
- method: `_filter_odds`

処理概要:

1. `bet_type is None` なら `RaceOdds` をほぼそのまま返す。
2. `bet_type` 指定時は `odds.odds.get(bet_type, [])` を `entries` に入れる。
3. `combination` 指定時は query 側だけ数字文字列を正規化する。
4. `entry.combination == normalized` で完全一致比較する。
5. 返却時は `bet_type` と `entries` を設定し、`odds` は空 dict にする。

## 現行の問題

順不同で扱うべき券種でも、list 順序が一致しないと絞り込みに失敗する。

例:

- entry: `["13", "17"]`
- query: `combination=17,13`
- 現行正規化後 query: `["17", "13"]`
- 比較結果: 不一致

## 現行で維持すべき仕様

- `bet_type` 未指定時は全券種を `odds` dict に入れて返す。
- `bet_type` 指定時は `entries` に対象券種のみを返す。
- unsupported `bet_type` は `BadRequestError`。
- query 側の数字文字列は `05 -> 5` に正規化する。
- cache hit 時も `_filter_odds` を通す。

## 既存テスト

`tests/test_api.py` に以下がある。

- `/netkeiba/races/202605021211/odds?bet_type=wide&combination=13,17`
- `entries[0].combination == ["13", "17"]`
- `odds_min == "5.1"`
- `odds_max == "5.6"`
- `popularity == "3"`

このテストは同順指定のみ確認している。

`tests/test_netkeiba_extractors.py` は payload parse 結果を確認しており、service の絞り込み仕様は直接検証していない。
