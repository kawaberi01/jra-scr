# v3 Derived Feature Iteration

Date: 2026-07-04

## Objective

Test whether a new feature line built only from the current DB can produce a better train/validation balance than the current `v25` branch.

Added derived features:

- same-course historical top3 rate
- jockey recent top3 rate
- trainer recent top3 rate
- field size
- late-card bonus candidate

Implementation basis:

- `evaluate_v1_validation.py`
- no API change
- no extra scraping

## Tested theories

- `v31`: `v25` + same-course + jockey recent form + trainer recent form
- `v32`: `v31` + stronger jockey/trainer weights + large-field bonus
- `v34`: stronger same-course + stronger jockey form

Note:

- `v33` was a late-card score-bonus test, but that bonus is race-level constant and therefore does not change within-race ranking. It is not a meaningful score feature in the current architecture.

## Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | axis_top3 | tickets |
|---|---:|---:|---:|---:|---:|
| v25 | 1.0723 | 1.0313 | 0.9710 | 0.5564 | 575 |
| v31 | 1.0418 | 1.0009 | 0.9399 | 0.5582 | 576 |
| v32 | 1.0364 | 0.9957 | 0.9351 | 0.5618 | 579 |
| v34 | 1.0465 | 1.0057 | 0.9450 | 0.5618 | 578 |

## Train walk-forward

| theory | Jul no-max | Aug no-max | Sep no-max | train floor |
|---|---:|---:|---:|---:|
| v25 | 0.8815 | 0.8570 | 0.5614 | 0.5614 |
| v31 | 0.6996 | 0.8383 | 0.5784 | 0.5784 |
| v32 | 0.6590 | 0.8685 | 0.5784 | 0.5784 |
| v34 | 0.7056 | 0.8950 | 0.5819 | 0.5819 |

## Reading

1. The derived-feature line did not create a candidate.
2. `v34` is the best of the new set, but it still fails badly on train.
3. Compared with `v25`, the new line slightly improves:
   - axis top3
   - Sep train floor
4. But that improvement is bought by a large Jul deterioration and weaker validation no-max.
5. So these derived features have signal, but the current weighting style is not enough.

## Practical conclusion

This iteration does not justify a holdout candidate.

Decision:

- `v31`: reject
- `v32`: reject
- `v34`: reject

## What was learned

- same-course and jockey/trainer context do change ranking behavior
- they are not strong enough yet as simple additive bonuses on top of `v25`
- race-level constants such as a plain late-card bonus should not be modeled as score terms, because they do not affect within-race ranking

## Next move

The next useful experiment should be one of these:

1. convert jockey/trainer/course context into target-side filters rather than small score bonuses
2. build conditional features such as:
   - jockey recent form under same surface
   - trainer recent form under same course/distance bucket
   - field-size interaction with middle-odds band
3. stop relying only on additive score tuning and test a two-stage rule:
   - choose axis by history score
   - filter middles by target-race context profile
