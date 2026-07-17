# V89 単独仮説探索

- 状態: exploratory_only
- 既知validation/holdoutを使うため、採用・昇格の根拠にはしない。

## validation

| 仮説 | 点数 | ROI | no-max ROI | no-top3 ROI |
| --- | ---: | ---: | ---: | ---: |
| baseline | 12 | 2.150 | 1.645 | 0.767 |
| axis_base_rank_le_3 | 8 | 3.225 | 2.586 | 1.380 |
| axis_odds_2_5_to_10 | 4 | 2.800 | 1.767 | 0.000 |
| axis_base_rank_le_3_and_odds_2_5_to_10 | 2 | 5.600 | 5.300 | 0.000 |

## known_holdout

| 仮説 | 点数 | ROI | no-max ROI | no-top3 ROI |
| --- | ---: | ---: | ---: | ---: |
| baseline | 33 | 1.536 | 1.328 | 0.970 |
| axis_base_rank_le_3 | 24 | 2.112 | 1.848 | 1.386 |
| axis_odds_2_5_to_10 | 15 | 1.200 | 0.764 | 0.000 |
| axis_base_rank_le_3_and_odds_2_5_to_10 | 10 | 1.800 | 1.189 | 0.000 |
