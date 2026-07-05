# Single Middle Iteration

Date: 2026-07-04

## Objective

Test whether some `insufficient_middle_candidates:1` races should still be bet with one ticket when the race shape is strong enough.

Rule added:

- allow a single middle candidate only when:
  - axis-score gap is large
  - middle odds / axis odds ratio is large

## New Theories

- `v17`: `v11` + allow one middle when `axis_score_gap > 10` and `odds_ratio > 5`
- `v18`: `v11` + allow one middle when `axis_score_gap > 10` and `odds_ratio > 3`

## Validation 2025Q4

| theory | ROI | no-max ROI | axis_top3 | bet_races | tickets |
|---|---:|---:|---:|---:|---:|
| v11 | 1.0356 | 1.0072 | 0.5309 | 416 | 832 |
| v17 | 1.0402 | 1.0124 | 0.5309 | 432 | 848 |
| v18 | 1.0412 | 1.0142 | 0.5309 | 457 | 873 |

## Train Walk-Forward

| theory | Jul ROI | Aug ROI | Sep ROI | Jul no-max | Aug no-max | Sep no-max |
|---|---:|---:|---:|---:|---:|---:|
| v11 | 0.9523 | 0.7808 | 0.6000 | 0.8713 | 0.7380 | 0.5504 |
| v17 | 0.9601 | 0.7812 | 0.6264 | 0.8812 | 0.7401 | 0.5787 |
| v18 | 0.9659 | 0.7659 | 0.6306 | 0.8898 | 0.7257 | 0.5847 |

## Findings

1. The single-middle override is the first post-`v11` change that improves validation instead of degrading it.
2. `v17` is slightly better than `v11` on validation and also slightly better in July and September train.
3. `v18` gives the best validation metrics, but August train gets worse than `v11`.
4. Even with the improvement, August and September train remain far below release level. No theory in this iteration is stable enough for holdout promotion.

## Decision

Keep `v17` and `v18` as informative candidates, but do not advance them as release candidates.

The signal is directionally useful because it recovers profitable validation races without obvious overfitting to one payout. But by itself it does not solve the weak train months.

## Next Hypothesis

Combine the single-middle override with a stronger race filter for poor race shapes, likely one of:

- suppress two-middle bets when odds ratio is too compressed
- suppress bets when axis odds are mid-range and score dispersion is weak
- split evaluation logic between one-middle override races and standard two-middle races
