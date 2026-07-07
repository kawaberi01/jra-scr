Date: 2026-07-07

# v89 Main-Venue Branch Decision

## Scope

Formalize the group-application idea as a concrete candidate branch.

- version: `v89`
- base: `v86`
- applied venues:
  - Tokyo (`05`)
  - Nakayama (`06`)
  - Kyoto (`08`)
  - Hanshin (`09`)
- excluded from betting:
  - local venues
  - Chukyo

This is not a new scoring theory. It is `v86` with a main-venue application gate.

## Rule

`v89 = v86 + allowed_course_codes ("05", "06", "08", "09")`

## Results

### Train walk-forward

| split | tickets | ROI | no-max ROI | note |
|---|---:|---:|---:|---|
| `wf1_2025_07` | 0 | n/a | n/a | no main-venue bets |
| `wf2_2025_08` | 0 | n/a | n/a | no main-venue bets |
| `wf3_2025_09` | 8 | 2.4750 | 1.6000 | usable sample |

Source:

- `train_walkforward_v89.json`
- `train_walkforward_v89.md`

### Validation

Period: `2025-10-01..2025-12-31`

- tickets: `12`
- hits: `5`
- ROI: `2.1500`
- no-max ROI: `1.5083`
- no-top3 ROI: `0.5750`

Source:

- `v89_validation_summary.json`
- `v89_validation_report.md`
- `v89_validation_races.json`

### Holdout

Period: `2026-01-01..2026-06-28`

- tickets: `33`
- hits: `9`
- ROI: `1.5364`
- no-max ROI: `1.2879`
- no-top3 ROI: `0.8818`

Source:

- `v89_holdout_summary.json`
- `v89_holdout_report.md`
- `v89_holdout_races.json`

## Interpretation

The main-venue branch is stronger than the all-venue interpretation of `v86`.

Positive points:

- validation ROI and no-max ROI are both strong
- holdout ROI and no-max ROI are both above 1.0
- Chukyo weakness is removed without using `skip Chukyo` as the only story
- the branch has a clearer operational meaning than full all-venue application

Weak points:

- July and August walk-forward have zero main-venue bets
- validation has only 12 tickets
- holdout no-top3 ROI is below 1.0
- this branch cannot satisfy the original monthly walk-forward gate because two train splits have no applicable bets

## Decision

Decision: **continue as the next operating candidate, not final adoption**

Status labels:

- numeric status: `promising`
- structural status: `reasonable`
- promotion status: `not_final`
- operating status: `main-venue candidate`

## Why this is not final adoption

`v89` should not be called final because:

1. train walk-forward coverage is incomplete
2. validation ticket count is still small
3. holdout no-top3 ROI is below 1.0
4. the original fixed gate was not designed for venue-group branches

## What changes from v86

Previous handling:

- `v86`: active reference line, all venues mixed

New handling:

- `v89`: main-venue candidate branch
- `v86_local`: separate watch branch
- `v86_chukyo`: reject for betting / diagnostic only

## Next step

Do not tune the scoring weights yet.

Next evaluation should be:

1. define a venue-group gate protocol
2. evaluate `v89_main` under that protocol
3. evaluate `v86_local` separately
4. decide whether production output should show:
   - `main`: actionable
   - `local`: reference only
   - `chukyo`: no bet

## Final verdict

`v89` is the correct next branch to pursue.

It is **better structured than v88** and **more operationally honest than all-venue v86**.
It is not yet a final adopted theory.
