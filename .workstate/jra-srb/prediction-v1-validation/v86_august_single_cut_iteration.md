Date: 2026-07-05

# v86 August Single-Cut Iteration

## Goal

Check whether `v86` can be improved by adding exactly one more pre-race ticket cut aimed at the remaining noise in `wf2_2025_08`.

## Fixed starting point

- theory: `v86`
- current fixed-gate blocker:
  - `wf2_2025_08 no-max ROI = 0.9187`

Base `v86` metrics:

| split | tickets | no-max ROI |
|---|---:|---:|
| `wf1_2025_07` | 10 | 1.1200 |
| `wf2_2025_08` | 16 | 0.9187 |
| `wf3_2025_09` | 10 | 1.7800 |
| `validation_2025Q4` | 22 | 1.4364 |
| `holdout_2026H1` | 48 | 1.2417 |

## Existing v86 follow-up sweep result

The existing single-filter sweep does **not** contain a clean fix inside the current `v86` ticket-context predicates.

Best near-miss from the recorded sweep:

- `exclude_middle_trainer_recent_top3_rate=0_25_0_35`
  - train floor: `0.9714`
  - validation: `0.8889`
  - holdout: `1.3860`

This improves August, but breaks validation.

## August loss shape

`wf2_2025_08` has:

- `16` tickets
- `5` hits
- `11` losses

Observed loss concentration from the saved race outputs:

- race number:
  - `8R`: `3` losses
- axis odds:
  - `<= 2.5`: `6` losses
  - `2.5 .. 4.0`: `5` losses
- course code:
  - `07` appeared repeatedly among August losses

## Additional one-cut hypotheses checked from saved v86 race outputs

Only pre-race-available cuts were considered here.

### Candidate A: exclude `race_no = 8`

| split | tickets | no-max ROI |
|---|---:|---:|
| `wf1_2025_07` | 7 | 0.9714 |
| `wf2_2025_08` | 13 | 1.1308 |
| `wf3_2025_09` | 8 | 1.6000 |
| `validation_2025Q4` | 18 | 1.5500 |
| `holdout_2026H1` | 40 | 1.0325 |

Result:

- August improves above `1.0`
- but `wf1_2025_07` falls below `1.0`
- reject

### Candidate B: exclude course code `07` (`中京`)

| split | tickets | no-max ROI |
|---|---:|---:|
| `wf1_2025_07` | 8 | 1.4000 |
| `wf2_2025_08` | 12 | 1.2250 |
| `wf3_2025_09` | 10 | 1.7800 |
| `validation_2025Q4` | 21 | 1.5048 |
| `holdout_2026H1` | 44 | 1.2182 |

Result:

- this is the only checked one-cut hypothesis in this pass that lifts August above `1.0`
- and keeps all observed train / validation / holdout splits above `1.0`

## Interpretation

At this point the result is:

1. No previously recorded `v86` ticket-context single filter fixes August cleanly.
2. A new coarse single cut, `exclude course_code=07 (中京)`, does clear all observed splits in the saved-output replay.

This should be treated carefully:

- it is operationally usable because `course_code` is known pre-race
- but it is also high-risk for venue overfit because it removes one full venue

## Practical decision

Shortest next step:

- treat `exclude course_code=07` as a **test hypothesis**, not immediate promotion
- if we continue this branch, the next artifact should be a formal `v86 + skip Chukyo` evaluation run and memo

Current judgment:

- `v86 + one extra learned ticket-context filter`: no clean solution found
- `v86 + one coarse venue cut`: possible, but overfit risk is obvious and must be documented explicitly
