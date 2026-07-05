# First Middle Gap Iteration

Date: 2026-07-04

## Objective

Test whether a race-confidence rule on the first middle candidate can improve train robustness without losing the validation edge from `v11`.

## New Theories

- `v14`: `v11` + require first middle `axis_score_gap > 5.0`
- `v15`: `v11` + require first middle `axis_score_gap > 10.0`
- `v16`: `v9` + require first middle `axis_score_gap > 5.0`

## Validation 2025Q4

| theory | ROI | no-max ROI | axis_top3 | bet_races | tickets |
|---|---:|---:|---:|---:|---:|
| v11 | 1.0356 | 1.0072 | 0.5309 | 416 | 832 |
| v14 | 0.9958 | 0.9646 | 0.5309 | 379 | 758 |
| v15 | 0.9977 | 0.9656 | 0.5309 | 368 | 736 |
| v16 | 0.9934 | 0.9528 | 0.4964 | 386 | 772 |

## Train Walk-Forward

| theory | Jul ROI | Aug ROI | Sep ROI | Jul no-max | Aug no-max | Sep no-max |
|---|---:|---:|---:|---:|---:|---:|
| v11 | 0.9523 | 0.7808 | 0.6000 | 0.8713 | 0.7380 | 0.5504 |
| v14 | 0.9708 | 0.7279 | 0.6134 | 0.8848 | 0.6966 | 0.5603 |
| v15 | 0.9494 | 0.6879 | 0.6711 | 0.8600 | 0.6561 | 0.6134 |
| v16 | 0.9080 | 0.8774 | 0.6620 | 0.8225 | 0.7905 | 0.6081 |

## Findings

1. `v14` and `v15` reduce bet count, but they destroy the validation edge from `v11`.
2. `v14` is worse than `v11` in August train, and only marginally better in September.
3. `v15` improves September over `v11`, but August degrades too much and validation falls below `1.0`.
4. `v16` improves August and September versus `v9`, but still fails validation and remains well below release level.

## Decision

The first-middle score-gap rule is not the next release path.

It cuts too many tickets in validation before it fixes the weak train months. This is a sign that the problem is not just "middle candidate too close to axis" but a broader race-shape or market-structure issue.

## Next Hypothesis

Move to a different signal family:

- race-shape dispersion across top candidates
- odds-balance between axis and the next candidate
- different handling for one-middle and two-middle races
