# netkeiba odds combination 正規化 前提メモ

## 対象

- Project: `jra-srb`
- Feature: `netkeiba-odds-combination-normalization`
- 対象 API:
  - `GET /netkeiba/races/{race_id}/odds`
- 対象実装:
  - `D:\develop\jra-scr\src\jra_srb\netkeiba_service.py`
  - 必要に応じて `D:\develop\jra-scr\tests\test_api.py`
  - 必要に応じて netkeiba service 専用テストを新規追加

## ユーザー要件

netkeiba odds API の `combination` 絞り込みで、券種に応じて順序性を扱い分ける。

順不同として扱う券種:

- `bracket_quinella`
- `quinella`
- `wide`
- `trio`

順序ありとして扱う券種:

- `exacta`
- `trifecta`

単一馬券種:

- `win`
- `place`

## 現在確認した実コード

`NetkeibaService._filter_odds` は、`bet_type` 未指定時に `RaceOdds.odds` をそのまま返す。

`bet_type` 指定時は `odds.odds.get(bet_type, [])` から対象 entry を取り出し、`combination` が指定されていれば次の比較を行う。

```python
normalized = [str(int(item)) if item.isdigit() else item for item in combination]
entries = [entry for entry in entries if entry.combination == normalized]
```

このため、query 側は `05 -> 5` に正規化されるが、比較は list の完全一致であり、順不同券種でも指定順に依存する。

## 実装境界

変更してよい範囲:

- `src/jra_srb/netkeiba_service.py`
- netkeiba odds API のテスト

変更しない範囲:

- 既存 JRA 公式 API 側の service / provider / extractor
- netkeiba odds payload の parse 仕様
- fixture HTML / JSON の構造
- DB 保存処理
- 大量取得処理

## 注意点

- entry 側と query 側の両方に同じ正規化を適用する。
- `bet_type` 未指定時の全件返却は現状維持する。
- `exacta` と `trifecta` は順序を維持する。
- `05` のような数字文字列は `5` として比較する。
