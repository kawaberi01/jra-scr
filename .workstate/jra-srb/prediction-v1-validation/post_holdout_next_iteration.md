# Post-Holdout Next Iteration

## Current State

- Frozen candidate `v10` failed holdout.
- Holdout data itself is complete and audited.
- The failure is model behavior, not a remaining holdout data defect.

## Rule

Do not tune `v10` from holdout 2026-01-01..2026-06-28.

Any modified theory must be a new version line evaluated only on:

- train: 2025-01-05..2025-09-30
- validation: 2025-10-01..2025-12-31

## Immediate Blocker

Train-period JRA official data is present, but train-period netkeiba evaluation data is not.

Audit result for 2025-01-01..2025-09-30:

- JRA races: 2615
- netkeiba mapped races: 0
- netkeiba result races: 48
- netkeiba payout races: 48

So train-period walk-forward evaluation is not ready.

Current walk-forward check with `v10`:

- WF1 2025-07: candidate 288 / evaluated 0 / excluded 288
- WF2 2025-08: candidate 360 / evaluated 0 / excluded 360
- WF3 2025-09: candidate 240 / evaluated 0 / excluded 240
- top exclusion reason in all three splits: `missing_netkeiba_mapping`

## Required Next Work

1. Fill netkeiba mappings for 2025-01-01..2025-09-30.
2. Fill netkeiba result/payout data for 2025-01-01..2025-09-30.
3. Add train walk-forward evaluation splits.
4. Generate new hypotheses from train and compare them on walk-forward + 2025Q4 validation.
5. Freeze the next candidate before any new holdout run.
