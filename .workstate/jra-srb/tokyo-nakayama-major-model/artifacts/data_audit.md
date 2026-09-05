# 東京・中山主要場モデル データ監査

- generated_at: `2026-09-05T09:24:51`
- db: `data\db\analysis.sqlite`
- 全JRA race: 7675 (2024-01-06..2026-09-05)
- 東京・中山 race: 2130 / {'nakayama': 1092, 'tokyo': 1038}

## 期間別coverage

| period | races | date | result | entries | payout | odds | laps |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| all | 2130 | 2024-01-06..2026-05-10 | 2130 | 2130 | 2130 | 0 | 1010 |
| known_train | 719 | 2025-01-05..2025-09-28 | 719 | 719 | 719 | 0 | 697 |
| known_validation | 324 | 2025-10-04..2025-12-28 | 324 | 324 | 324 | 0 | 313 |
| known_holdout | 463 | 2026-01-04..2026-05-10 | 463 | 463 | 463 | 0 | 0 |
| post_known_holdout | 0 | None..None | 0 | 0 | 0 | 0 | 0 |

## セグメント

- surface: `{'ダート': 1191, '芝': 939}`
- class split: `{'flat_general': 2087, 'obstacle': 43}`
- field size: `{'11_13': 392, 'ge_14': 1515, 'le_10': 223}`
- payout types: `{'3連単': 2149, '3連複': 2138, 'ワイド': 6406, '単勝': 2132, '枠連': 2068, '複勝': 6373, '馬単': 2141, '馬連': 2139}`
- post-known rows: `[]`

## as-of odds

- bet types: `{}`
- timing labels: `{}`
- timestamp comparison: `{'parsed': 0, 'before_start': 0, 'at_or_after_start': 0, 'unparseable': 0}`

## 監査上の扱い

- `at_or_after_start` のsnapshotは購入判断に使用しない。
- 実取得oddsがない券種は候補を生成しない。
- 新馬・障害は一般平地集計から分離する。
