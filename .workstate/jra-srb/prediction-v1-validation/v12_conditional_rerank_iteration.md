# v12 conditional rerank iteration

Date: 2026-07-05

## Objective

Test whether the useful part of `v70` can be isolated without paying the July train penalty.

The working hypothesis was:

- the validation gain needs both
  - weaker `middle_large_field_odds_over_10_penalty`
  - conditional removal of `middle_same_dist_0_25_0_35_bonus`
- but the bonus should only be removed when the axis is strongly favored

## Candidates

- `v75`: `v68` plus disable `middle_same_dist_0_25_0_35_bonus` when `axis_odds <= 2.0`
- `v76`: same, threshold `<= 2.5`
- `v77`: same, threshold `<= 3.0`

## Results

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max |
|---|---:|---:|---:|---:|
| v60 | 0.9553 | 1.0167 | 0.9453 | 1.0353 |
| v70 | 1.0350 | 0.8611 | 0.9453 | 1.0353 |
| v75 | 1.0350 | 1.0167 | 0.9453 | 1.0353 |
| v76 | 1.0350 | 1.0167 | 0.9453 | 1.0353 |
| v77 | 1.0350 | 1.0167 | 0.9453 | 1.0353 |

## Findings

1. The combination hypothesis was correct.
2. `v75` reproduces the validation lift from `v70` without degrading walk-forward no-max.
3. `v76` and `v77` are identical in outcome, so the extra threshold range does not add value.

## Race-level change

Validation changed in only 2 races relative to `v60`:

- `202511220304`: `['5-12'] -> ['5-7']`, payout `0 -> 830`
- `202512060607`: `['5-9'] -> ['5-6']`, payout `330 -> 320`

July walk-forward changed in only 1 race:

- `202507190204`: `['4-10'] -> ['4-8']`, payout `0 -> 0`

So the train no-max stayed unchanged because the only July difference was a losing ticket swap.

## Decision

Promote `v75` as the new frontier.

Keep `v76` and `v77` only as confirmation that the wider threshold does not matter on the current data.

## Holdout result

`v75` was then frozen and run on holdout `2026-01-01..2026-06-28`.

- ROI: `0.7672`
- no-max ROI: `0.6497`
- verdict: reject

So `v75` is the best validation candidate in this branch, but it is not a surviving theory.

## Next direction

The next branch should not continue rerank tuning.

Use this as the next exploration rule:

- shift from "buy the highest-scored middle" toward "buy only ticket shapes that remain stable"
- treat axis selection and partner selection as separate problems
- search for repeatable buy/skip ticket shapes on train walk-forward + validation only
