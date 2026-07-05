# v7 Axis Context Iteration

Date: 2026-07-04

## Purpose

Keep the successful `v46` middle-score idea, and change the axis choice itself.

This iteration:

- kept middle re-ranking by context bucket
- added axis-specific context adjustments before axis selection
- left the rest of the ticket logic unchanged

## Added Theory Line

- `v49`
  - stronger axis context adjustments
  - reward stronger same-distance and same-surface history
  - reward stronger jockey/trainer recent form
  - penalize weak same-distance / same-surface / recent-form buckets
- `v50`
  - lighter version of `v49`
- `v51`
  - conservative version using mostly same-distance and same-surface axis adjustments

## Train Walk-Forward

| theory | Jul no-max | Aug no-max | Sep no-max | train floor |
|---|---:|---:|---:|---:|
| v49 | 0.6789 | 0.8915 | 0.5614 | 0.5614 |
| v50 | 0.7498 | 0.8887 | 0.5614 | 0.5614 |
| v51 | 0.9172 | 0.8323 | 0.5614 | 0.5614 |

## Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | axis_top3 | tickets |
|---|---:|---:|---:|---:|---:|
| v49 | 1.0635 | 1.0223 | 0.9611 | 0.5655 | 573 |
| v50 | 1.0532 | 1.0120 | 0.9508 | 0.5618 | 573 |
| v51 | 1.0402 | 0.9990 | 0.9383 | 0.5582 | 572 |

## Reading

1. This is the first no-new-data branch in this session where validation no-max cleared 1.0.
2. `v49` is the best of the three on validation.
3. Axis-top3 improved a little, which is consistent with the intended change.
4. However, the train floor did not improve at all on the key weak split `wf3_2025_09`.
5. In `v49` and `v50`, Jul train got worse while validation improved.
6. `v51` preserved Jul better, but lost the validation no-max edge.

## Decision

- `v49`: reject before holdout
- `v50`: reject before holdout
- `v51`: reject before holdout

Reason:

- the fixed gate requires train walk-forward and validation together
- all three theories still fail on train, especially `wf3_2025_09 = 0.5614`

## What was learned

- axis context matters more than the previous hard-filter iterations suggested
- validation can be improved materially without new data
- the remaining bottleneck is now concentrated in the train-side weak month pattern, not in headline validation
- `v49` is the current best no-new-data theory in this thread, but still not promotable

## Practical next move

If we stay in the no-new-data branch, the next useful step is no longer broad rule invention.

The next focused work should be:

1. compare `v49` winning races against `wf3_2025_09` failures
2. identify what race pocket causes the Sep collapse
3. add one narrowly targeted guard only for that pocket

So the branch has now moved from "not working" to "close on validation, still broken on train".
