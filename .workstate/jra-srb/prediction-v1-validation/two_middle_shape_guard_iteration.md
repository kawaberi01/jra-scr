# Two-Middle Shape Guard Iteration

Date: 2026-07-04

## Objective

Keep the useful `single-middle` override from `v17`, and separately suppress weak standard two-middle races that show compressed market shape.

## New Theories

- `v19`: `v17` + skip standard bets when `axis_odds <= 4.0` and `first_middle_odds_ratio <= 3.0`
- `v20`: `v17` + skip standard bets when `axis_odds <= 6.0` and `first_middle_odds_ratio <= 2.0`

## Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | axis_top3 | bet_races | tickets |
|---|---:|---:|---:|---:|---:|---:|
| v17 | 1.0402 | 1.0124 | 0.9667 | 0.5309 | 432 | 848 |
| v19 | 1.0676 | 1.0379 | 0.9893 | 0.5309 | 406 | 796 |
| v20 | 1.0503 | 1.0202 | 0.9708 | 0.5309 | 400 | 784 |

## Train Walk-Forward

| theory | Jul ROI | Aug ROI | Sep ROI | Jul no-max | Aug no-max | Sep no-max |
|---|---:|---:|---:|---:|---:|---:|
| v17 | 0.9601 | 0.7812 | 0.6264 | 0.8812 | 0.7401 | 0.5787 |
| v19 | 0.9674 | 0.7981 | 0.5808 | 0.8837 | 0.7535 | 0.5259 |
| v20 | 0.9644 | 0.7978 | 0.5952 | 0.8822 | 0.7526 | 0.5464 |

## Findings

1. The compressed two-middle guard clearly helps validation.
2. `v19` is the strongest validation result seen so far:
   - ROI `1.0676`
   - no-max ROI `1.0379`
3. `v19` and `v20` both improve August slightly versus `v17`.
4. Both theories hurt September, especially `v19`.
5. This means the compressed-shape filter is useful for validation and part of train, but its current form is too broad and removes too many September winners.

## Decision

Do not promote `v19` or `v20` to holdout.

They improve the validation side of the objective, but they still fail the broader reproducibility requirement because late-train instability remains unresolved.

## Next Hypothesis

Refine the shape guard so it avoids damaging September:

- apply the guard only to standard two-middle races with `axis_odds <= 4.0`
- exempt races where the axis itself is very short (`<= 2.0`)
- test whether the bad segment is specifically `axis 2-4 and ratio 2-3`, not compressed shapes in general
