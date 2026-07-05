# v5 Context Profile Iteration

Date: 2026-07-04

## Purpose

Test the shortest no-new-data theory line:

- keep `v25` as the base axis / ticket structure
- stop doing only monotonic hard thresholds
- use context-profile filters for middle selection

Added context features from the current DB only:

- jockey recent top3 rate under the same surface
- trainer recent top3 rate under the same distance bucket
- same-distance rate bucket handling
- field-size bucket handling
- field-size x middle-odds guard

## Added Theories

- `v43`
  - same-distance buckets: `lt_0_15`, `0_25_0_35`
  - jockey same-surface buckets: exclude only `ge_0_35`
  - field size: `11_13`, `ge_14`
  - if `field_size >= 14`, require middle odds `<= 10.0`
- `v44`
  - `v43` plus trainer same-distance bucket filter
  - same-distance buckets: `lt_0_15`, `0_25_0_35`, `missing`
  - trainer same-distance buckets: `0_15_0_25`, `0_25_0_35`, `ge_0_35`
  - if `field_size >= 14`, require middle odds `<= 12.0`
- `v45`
  - same-distance buckets: `lt_0_15`, `0_25_0_35`, `missing`
  - field size: `11_13`, `ge_14`
  - if `field_size >= 14`, require middle odds `<= 10.0`
  - no trainer-side hard bucket filter

## Train Walk-Forward

| theory | Jul no-max | Aug no-max | Sep no-max | train floor |
|---|---:|---:|---:|---:|
| v43 | 0.0000 | 0.9192 | 0.0000 | 0.0000 |
| v44 | 0.0000 | 0.1700 | 0.2643 | 0.0000 |
| v45 | 0.5938 | 0.7920 | 0.0000 | 0.0000 |

## Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | axis_top3 | tickets |
|---|---:|---:|---:|---:|---:|
| v43 | 0.6947 | 0.5026 | 0.1868 | 0.5564 | 38 |
| v44 | 0.8000 | 0.5250 | 0.1393 | 0.5564 | 28 |
| v45 | 0.9394 | 0.8042 | 0.5563 | 0.5564 | 71 |

## Reading

1. This no-new-data context-profile branch did not produce a candidate.
2. `v45` is the best of the set.
3. The new context filters reduced ticket count too aggressively in `v43` and `v44`.
4. `v45` retained more races and came closest to break-even on validation, but still failed clearly.
5. The main failure is unchanged: once the rule tries to protect validation shape, one or more train splits collapse.

## Decision

- `v43`: reject
- `v44`: reject
- `v45`: reject

## What was learned

- same-distance bucket handling is more useful than trainer-side hard context pruning
- field-size x middle-odds interaction is directionally better than plain field-size filtering
- aggressive middle-pruning causes too few tickets and unstable outcomes
- within the no-new-data rule-based branch, there is still signal, but not enough for promotion

## Practical next move

If staying in the no-new-data path, the next attempt should be narrower than adding more hard filters:

1. keep `v45` as the better base
2. move from hard allow/deny buckets to small score adjustments by context bucket
3. test only 2-3 variants, not another broad threshold sweep
