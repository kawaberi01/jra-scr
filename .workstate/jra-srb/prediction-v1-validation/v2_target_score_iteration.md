# v2 Target Score Iteration

Date: 2026-07-04

## Objective

`v2` の初期 hard gate 版では target-race feature が効くことは確認できたが、
`wf3_2025_09` の改善が足りなかった。

そこで次の仮説を確認した。

- `axis popularity`
- `horse_weight_diff`

を gate ではなく score bonus / penalty として候補順位に反映すれば、
month-to-month の歪みが減るか。

## Implementation

変更:

- `evaluate_v1_validation.py` に target-race score adjustment を追加
- popularity:
  - `<=3` bonus
  - `4-6` penalty
  - `7+` penalty
- abs weight diff:
  - `1-4` bonus
  - `5-8` penalty
  - `9+` penalty

評価候補:

- `v27`: popularity + weight diff の基本 score 版
- `v28`: popularity penalty を強め、weight penalty を軽くした版
- `v29`: popularity を少し弱め、weight diff を強めた版
- `v30`: popularity score のみ

## Results

### Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | axis_top3 |
|---|---:|---:|---:|---:|
| v24 | 1.0874 | 1.0564 | 1.0064 | 0.5564 |
| v25 | 1.0723 | 1.0313 | 0.9710 | 0.5564 |
| v27 | 0.9562 | 0.9199 | 0.8758 | 0.5527 |
| v28 | 0.8970 | 0.8728 | 0.8348 | 0.5509 |
| v29 | 0.9564 | 0.9199 | 0.8755 | 0.5382 |
| v30 | 1.0036 | 0.9793 | 0.9387 | 0.5509 |

### Train walk-forward

| theory | Jul ROI | Aug ROI | Sep ROI | Jul no-max | Aug no-max | Sep no-max |
|---|---:|---:|---:|---:|---:|---:|
| v24 | 0.8608 | 0.8506 | 0.5583 | 0.7753 | 0.8069 | 0.5078 |
| v25 | 0.9928 | 0.9155 | 0.6313 | 0.8815 | 0.8570 | 0.5614 |
| v27 | 0.8336 | 0.9417 | 0.6213 | 0.7573 | 0.9011 | 0.5616 |
| v28 | 0.8471 | 0.9239 | 0.5019 | 0.7708 | 0.8834 | 0.4684 |
| v29 | 0.8240 | 0.9441 | 0.6087 | 0.7468 | 0.9033 | 0.5490 |
| v30 | 0.9697 | 0.9140 | 0.5966 | 0.8934 | 0.8735 | 0.5369 |

## Interpretation

1. score 版は `2025-08` を押し上げるが、validation で大きく崩れた
2. `v30` は popularity だけに絞れば validation 崩れは軽いが、それでも no-max は `0.9793`
3. hard gate 版 `v24/v25` のほうが validation の再現性は明確に良い
4. つまり、今回入れた target-race feature は「候補順位を全面的に動かす」より「購入 gate として使う」ほうがまだまし

## Decision

この iteration では holdout 候補は出ていない。

- `v27`: 不採用
- `v28`: 不採用
- `v29`: 不採用
- `v30`: 不採用

また、score 版は hard gate 版 `v24/v25` より後退したため、
この方向をそのまま掘る優先度は低い。

## Updated conclusion

現時点の `v2` 探索では、最良に近い位置はまだ `v25`。

- validation は基準超え
- `2025-08` はかなり改善
- ただし `2025-09` が足りない

したがって次の合理的な分岐は以下のどちらか。

1. `v25` を土台に、target-race feature と race-shape guard を組み合わせる
2. 新しい target-race feature を足す

優先は `1`。

特に次に試す価値があるのは、
`v25` の middle weight-diff gate を保ったまま、
`axis_odds × odds_ratio` の軽い shape guard を重ねる枝。
