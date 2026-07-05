# v6 Middle Score Iteration

Date: 2026-07-04

## Purpose

Continue the no-new-data path without hard middle pruning.

This iteration kept the base `v25` / `v45` structure, but changed only the
middle ranking step:

- axis selection stays on the original score
- middle candidates are re-ranked by `base score + context-bucket adjustment`

## Added Theory Line

- `v46`
  - same-distance bucket bonuses and penalties
  - jockey same-surface bucket bonuses and penalties
  - small-field penalty
  - large-field bonus
  - large-field + middle odds > 10 penalty
- `v47`
  - lighter version of `v46`
- `v48`
  - `v47` plus mild trainer same-distance bonus

## Train Walk-Forward

| theory | Jul no-max | Aug no-max | Sep no-max | train floor |
|---|---:|---:|---:|---:|
| v46 | 0.9048 | 0.8323 | 0.5614 | 0.5614 |
| v47 | 0.9048 | 0.8323 | 0.5614 | 0.5614 |
| v48 | 0.8775 | 0.8323 | 0.5614 | 0.5614 |

## Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | axis_top3 | tickets |
|---|---:|---:|---:|---:|---:|
| v46 | 1.0281 | 0.9869 | 0.9264 | 0.5564 | 573 |
| v47 | 1.0281 | 0.9869 | 0.9264 | 0.5564 | 573 |
| v48 | 1.0281 | 0.9869 | 0.9264 | 0.5564 | 573 |

## Reading

1. This branch is much better than the hard-filter `v43..v45` branch.
2. Validation headline ROI recovered above 1.0.
3. But validation no-max is still below 1.0, so it is not robust enough.
4. Train still fails on the same floor as the old `v25` family, especially `wf3_2025_09`.
5. `v46` and `v47` produced identical results, and `v48` changed only one train split slightly.
6. That means the middle context adjustments are directionally valid, but not strong enough to change the practical candidate set very much.

## Decision

- `v46`: reject
- `v47`: reject
- `v48`: reject

## What was learned

- changing middle ranking is better than hard middle filtering
- context buckets can restore validation ROI without collapsing ticket count
- however, this version line still inherits the old `v25` train weakness
- mild trainer-side context adds almost no value here

## Practical next move

If we continue without new data, the next target should be:

1. keep the middle-score idea
2. stop treating the axis score as fixed
3. test a version where axis selection itself also uses context-sensitive scoring

At this point, the no-new-data branch has improved from "clearly unusable" to
"near break-even on robust validation", but it still does not clear the train +
validation gate.
