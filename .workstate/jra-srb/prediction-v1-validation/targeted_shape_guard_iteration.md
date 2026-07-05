# Targeted Shape Guard Iteration

Date: 2026-07-04

## Objective

Narrow the compressed-shape guard so that validation gains remain, while avoiding the September regression seen in `v19` and `v20`.

## New Theory

- `v21`: `v17` + skip standard two-middle bets only when:
  - `axis_odds` is in `(2.0, 4.0]`
  - `first_middle_odds_ratio` is in `[2.0, 3.0)`

## Results

### Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | bet_races | tickets |
|---|---:|---:|---:|---:|---:|
| v17 | 1.0402 | 1.0124 | 0.9667 | 432 | 848 |
| v21 | 1.0649 | 1.0353 | 0.9868 | 407 | 798 |

### Train Walk-Forward

| theory | Jul ROI | Aug ROI | Sep ROI | Jul no-max | Aug no-max | Sep no-max |
|---|---:|---:|---:|---:|---:|---:|
| v17 | 0.9601 | 0.7812 | 0.6264 | 0.8812 | 0.7401 | 0.5787 |
| v21 | 0.9674 | 0.7981 | 0.5808 | 0.8837 | 0.7535 | 0.5259 |

## Findings

1. The narrower guard preserved almost all of the validation benefit.
2. It did not fix the September regression. `v21` ended up effectively matching the `v19` train profile.
3. Therefore the September weakness is not explained only by the `axis 2-4 / ratio 2-3` segment.

## Decision

`v21` is not a holdout candidate.

It is strong on validation, but still fails the broader reproducibility goal because the weak train month remains unresolved.

## Updated Hypothesis

The next useful split is likely not just market compression. The remaining issue is probably one of:

- course or month-specific race-shape behavior
- a weakness in the scoring function itself, not only the betting gate
- standard two-middle races with `axis 2-4 / ratio > 5` or `axis 4-6 / ratio 3-5`, which were still poor in September
