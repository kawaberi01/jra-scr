Date: 2026-07-05

# v88 Formal Adoption Decision

## Scope

This memo turns `v88` from an exploratory branch into a formal decision artifact.

- candidate: `v88`
- base: `v86`
- added rule: `excluded_course_codes = ("07",)` (`Chukyo` exclusion)

## Evaluation evidence

### Train walk-forward

| split | tickets | ROI | no-max ROI |
|---|---:|---:|---:|
| `wf1_2025_07` | 8 | 2.5125 | 1.4000 |
| `wf2_2025_08` | 12 | 1.6250 | 1.2250 |
| `wf3_2025_09` | 10 | 2.4800 | 1.7800 |

Source:

- `train_walkforward_v88.json`
- `train_walkforward_v88.md`

### Validation

Period: `2025-10-01..2025-12-31`

- tickets: `21`
- ROI: `1.8714`
- no-max ROI: `1.5048`
- no-top3 ROI: `0.9571`

Source:

- `v88_validation_summary.json`
- `v88_validation_report.md`
- `v88_validation_races.json`

### Holdout

Period: `2026-01-01..2026-06-28`

- tickets: `44`
- ROI: `1.4045`
- no-max ROI: `1.2182`
- no-top3 ROI: `0.9136`

Source:

- `v88_holdout_summary.json`
- `v88_holdout_report.md`
- `v88_holdout_races.json`

## Numerical assessment

Under the current numeric gate only, `v88` is the first observed `v86`-derived line that clears:

1. all train walk-forward no-max splits
2. validation no-max
3. holdout no-max

On pure scorecard terms, this is a pass.

## Structural assessment

The added rule is not a horse-level, ticket-shape-level, or race-structure-level rule.
It is a full-venue exclusion.

That makes the branch weak in three ways:

1. the causal explanation is thin
2. the rule is too coarse relative to the rest of the theory
3. the improvement may mainly reflect a localized historical patch

The branch therefore improves the observed metrics without establishing a robust reusable betting theory.

## Adoption decision

Decision: **reject for formal adoption**

Status labels:

- numeric status: `pass`
- structural status: `reject`
- operational status: `diagnostic branch only`

## Why adoption is rejected

`v88` is rejected for formal adoption because:

1. the only added rule is `skip Chukyo`
2. that rule does not provide a defensible production rationale yet
3. adopting it would normalize venue-level patching as a way to clear evaluation gates
4. that would weaken the stated project goal of avoiding past-data overfit

## What v88 is still useful for

`v88` should still be retained as an important artifact because it demonstrates:

1. the remaining `v86` weakness is highly concentrated
2. venue-level stress pockets exist and are measurable
3. the current branch is close to passing numerically, but not in a way that should be trusted yet

## Final handling

- do not promote `v88` as an adopted theory
- do not use `v88` as the main user-facing theory label
- keep `v86` as the active reference line
- keep `v88` as a tracked diagnostic branch and comparison point

## Final verdict

`v88` is a **formal numeric pass but formal adoption reject**.

It is valid as evidence.
It is not valid as the final theory.
