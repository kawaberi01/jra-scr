# 南関 勝ちパターン分析 API エラー修正依頼

南関 勝ちパターン分析 API の不具合修正をお願いします。

## 対象

- `GET /nankankeiba/pattern/meetings/{date}/{course}/races/{race_no}?meeting_no={meeting_no}&meeting_day={meeting_day}`

## 不具合

- 一部レースで 500 になり、以下の例外で落ちます。

```python
TypeError: '<' not supported between instances of 'str' and 'int'
```

## 発生箇所

- `src/jra_srb/nankankeiba_pattern_service.py`
- `_merge_category_pages()`
- 末尾の並び替え部分

現状のコードイメージ:

```python
return [merged[key] for key in sorted(merged, key=lambda value: int(value) if value.isdigit() else value)]
```

## 再現できているレース

- 2026-07-06 川崎 8R
  - `GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/8?meeting_no=4&meeting_day=1`
- 2026-07-06 川崎 9R
  - `GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/9?meeting_no=4&meeting_day=1`

## 同日でも正常なレースあり

- 6R: 200
- 7R: 200
- 10R: 200

## やってほしいこと

### 1. 原因調査

- `merged` の key に、数値文字列と非数値文字列が混在しているケースを確認してください
- 何が混ざっているかを把握してください
  - 例: `"1"`, `"2"`, `"unknown"` のような混在
- どのカテゴリページのどの行から混ざるか確認してください

### 2. 修正方針

- ソートキーが常に比較可能な同一型を返すようにしてください
- 例えば以下のように、タプルで型を揃えてください

```python
def _runner_sort_key(value: str) -> tuple[int, object]:
    return (0, int(value)) if value.isdigit() else (1, value)
```

または同等の安全な実装にしてください。

イメージ:

```python
return [merged[key] for key in sorted(merged, key=_runner_sort_key)]
```

### 3. 期待仕様

- 数値の horse_no は数値順で並ぶ
- 非数値キーが混ざっても 500 にしない
- 非数値キーが本来不要なデータなら、その扱いを明確にしてください
  - 破棄するのか
  - 後ろに回すのか
- 少なくとも API 全体が落ちないことを優先してください

### 4. 追加テスト

最低限ほしいテスト:

- `_merge_category_pages()` に数値文字列キーと非数値キーが混在しても落ちない
- 数値 horse_no が `1,2,10` の順に並ぶ
- 問題レース相当の fixture で API が 200 を返す

### 5. 確認してほしいこと

修正後に以下を確認してください。

- `GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/8?meeting_no=4&meeting_day=1`
- `GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/9?meeting_no=4&meeting_day=1`

両方とも 200 で返ること。

## 補足

- この API は予想ロジックで `pattern_uma.track_condition_rates` や `pattern_uma.rates.kawasaki` を使う前提です
- 8R, 9R だけ落ちると、後半レースの検証が途中で止まります
- まずは「落ちないこと」を優先し、そのうえで並び順を安定させてください

## 実装後にまとめてほしいこと

- 原因
- 修正内容
- 追加したテスト
- 再確認結果
