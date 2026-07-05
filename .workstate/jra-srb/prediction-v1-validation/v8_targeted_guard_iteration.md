# v8 targeted guard iteration

Date: 2026-07-04

## Change
- Added `max_race_no_to_bet` to `TheoryConfig` and evaluation guard.
- Fixed `v53` so it actually skips race 9-12 via `max_race_no_to_bet=8`.
- Evaluated `v52` (axis popularity <= 2), `v53` (race 1-8 only), `v54` (field size >= 14).

## Train walk-forward
- `v52`: Jul no-max 0.5856 / Aug 0.7780 / Sep 0.6042
- `v53`: Jul no-max 0.6348 / Aug 0.8500 / Sep 0.6927
- `v54`: Jul no-max 0.7067 / Aug 0.9385 / Sep 0.5623

## Validation (2025-10-01..2025-12-31)
- `v52`: ROI 0.9419 / no-max 0.9179
- `v53`: ROI 1.1828 / no-max 1.0923
- `v54`: ROI 1.0842 / no-max 1.0279

## Decision
- `v52`: rejected. Axis popularity <= 2 cut too much and still left train weak.
- `v54`: rejected. Large-field-only helped validation but did not solve Sep train.
- `v53`: best targeted guard so far. It materially improves Sep train and keeps validation strong, but Jul no-max 0.6348 is still below adoption line.

## Interpretation
- The main instability is concentrated in late races (9-12).
- Skipping late races is the first simple guard that improves both Sep train and validation together.
- However, the guard is too coarse to be accepted as the single final theory because early-race subsets still do not clear all train splits.
- Shortest next step is to refine inside race 1-8 only, not across all races.
