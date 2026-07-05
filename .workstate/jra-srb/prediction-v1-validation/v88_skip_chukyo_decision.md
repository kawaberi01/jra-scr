Date: 2026-07-05

# v88 Skip-Chukyo Decision

## Theory

- version: `v88`
- base: `v86`
- added rule:
  - `excluded_course_codes = ("07",)` (`中京` を除外)

## Results

| split | tickets | no-max ROI |
|---|---:|---:|
| `wf1_2025_07` | 8 | 1.4000 |
| `wf2_2025_08` | 12 | 1.2250 |
| `wf3_2025_09` | 10 | 1.7800 |
| `validation_2025Q4` | 21 | 1.5048 |
| `holdout_2026H1` | 44 | 1.2182 |

Additional headline metrics:

- validation ROI: `1.8714`
- holdout ROI: `1.4045`

## Interpretation

`v88` is the first observed `v86`-derived one-cut variant that clears:

- all train walk-forward no-max splits
- validation no-max
- holdout no-max

However, the added rule is a full-venue exclusion.

That means:

1. the result is operationally simple
2. but the causal story is weak
3. and venue-level overfit risk is high

## Decision

Treat `v88` as:

- `numerically pass`
- `structurally suspicious`

Operational recommendation:

- do **not** call this a robust promoted theory yet
- keep it as a tracked branch showing that August noise is concentrated in `中京`
- use it only as a diagnostic frontier unless a domain reason for `中京` exclusion is found

## Artifacts

- `train_walkforward_v88.json`
- `train_walkforward_v88.md`
- `v88_validation_summary.json`
- `v88_validation_report.md`
- `v88_validation_races.json`
- `v88_holdout_summary.json`
- `v88_holdout_report.md`
- `v88_holdout_races.json`
