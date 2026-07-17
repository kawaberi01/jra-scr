# V89 オッズ断層ゲート探索

- 状態: exploratory_only
- 既知validation/holdoutを使うため、採用・昇格の根拠にはしない。

## validation

| 仮説 | 点数 | ROI | no-max ROI | no-top3 ROI |
| --- | ---: | ---: | ---: | ---: |
| baseline | 12 | 2.150 | 1.645 | 0.767 |
| axis_above_max_gap | 0 | 0.000 | 0.000 | 0.000 |
| middle_above_max_gap | 0 | 0.000 | 0.000 | 0.000 |
| either_above_max_gap | 0 | 0.000 | 0.000 | 0.000 |

## known_holdout

| 仮説 | 点数 | ROI | no-max ROI | no-top3 ROI |
| --- | ---: | ---: | ---: | ---: |
| baseline | 33 | 1.536 | 1.328 | 0.970 |
| axis_above_max_gap | 2 | 2.300 | 0.000 | 0.000 |
| middle_above_max_gap | 1 | 0.000 | 0.000 | 0.000 |
| either_above_max_gap | 3 | 1.533 | 0.000 | 0.000 |
