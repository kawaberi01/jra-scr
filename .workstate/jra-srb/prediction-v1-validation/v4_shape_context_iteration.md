# v4 Shape Context Iteration

Date: 2026-07-04

## Purpose

Current `v25` derivatives improved validation, but failed train walk-forward, especially `wf3_2025_09`.
This iteration checked whether ticket/race shape filters can reduce that failure without using holdout.

## Added Analysis

- `analyze_ticket_shape_context.py`
  - Groups `v25` tickets by race number, course, surface, field size, axis odds, middle odds, odds ratio, and popularity.
- `find_ticket_shape_filters.py`
  - Searches only 1-condition and 2-condition filters.
  - Requires at least 20 tickets in each train/validation split.
  - Ranks by train no-max floor, then validation no-max.

## Findings

Best 1-2 condition shape filter:

| conditions | train no-max floor | validation no-max | wf1 tickets | wf2 tickets | wf3 tickets | validation tickets |
|---|---:|---:|---:|---:|---:|---:|
| axis_odds <= 2.5 and surface = dirt | 0.7600 | 1.0128 | 38 | 44 | 30 | 94 |

This looked like the only defensible direction from the shape search, but it was still below the fixed train gate.

## Theory Added

`v42`

- base: `v25`
- surface filter: dirt only
- strict axis odds bet filter: `axis_odds <= 2.5`
- middle odds: `8.0..20.0`
- minimum middle count: `2`
- no holdout run

Implementation note:

- Added `surface_to_bet` and `max_axis_odds_to_bet` to `TheoryConfig`.
- `axis_odds_max` remains an axis-selection preference, so `max_axis_odds_to_bet` is required for a strict no-bet filter.

## v42 Results

| split | ROI | no-max ROI | top3-cut ROI | tickets | max payout | verdict |
|---|---:|---:|---:|---:|---:|---|
| wf1_2025_07 | 0.8483 | 0.6948 | 0.4931 | 58 | 890 | reject |
| wf2_2025_08 | 0.9266 | 0.8313 | 0.6578 | 64 | 610 | reject |
| wf3_2025_09 | 0.9400 | 0.7775 | 0.5600 | 40 | 650 | reject |
| validation_2025Q4 | 1.0242 | 0.9542 | 0.8200 | 120 | 840 | reject |

## Decision

`v42` is rejected before holdout.

Reason:

- train no-max floor is below 1.0
- validation no-max is below 1.0
- ticket count is lower than the main `v25` branch, so the apparent ROI is less reliable

## Updated Rule-Space Conclusion

After `v35..v42`, the scoreboard contains 78 theories and still has 0 candidates by the fixed train+validation gate.

The current evidence says:

- middle trainer/course hard filters overfit train pockets and lose validation edge
- field-size filters improve validation but do not fix `wf3_2025_09`
- strict dirt/low-axis-odds filtering improves hit rate, but does not produce positive no-max ROI

Therefore the current threshold/rule space is exhausted for promotion.

## Next Required Direction

Do not continue by only adding more hard thresholds to `v25`.

The next iteration should introduce a new feature family or model structure, then rerun the same gate:

- pre-race frame/post-position features
- target-race odds/popularity distribution features
- condition-specific jockey/trainer features
- course/class/age conditional features
- a simple learned scorer trained only on train data, validated once on 2025Q4, and held out on 2026H1 only after passing validation
