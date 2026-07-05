# v86 Reference-Line Decision

Date: 2026-07-05

## Purpose

This memo separates two judgments:

- fixed promotion gate
- reference-line judgment for practical theory exploration

The user requested that `v86` should continue as a **reference line**, even though it does not clear the fixed train walk-forward gate.

## Theory

- version: `v86`
- base: `v80`
- added ticket filters:
  - exclude `middle_jockey_recent_top3_rate = 0.15-0.25`
  - exclude `axis_odds = 4.0-6.0`

## Fixed-gate result

| split | no-max ROI |
|---|---:|
| `wf1_2025_07` | 1.1200 |
| `wf2_2025_08` | 0.9187 |
| `wf3_2025_09` | 1.7800 |
| `validation_2025Q4` | 1.4364 |
| `holdout_2026H1` | 1.2417 |

Under the fixed gate, `v86` is still **reject for promotion** because `wf2_2025_08 < 1.0`.

## Reference-line judgment

If `wf2_2025_08` is not used as a hard rejection month, `v86` becomes the strongest observed theory in the current no-new-data ticket-shape line.

Reference-line view:

- `wf1_2025_07`: pass
- `wf3_2025_09`: pass
- `validation_2025Q4`: pass
- `holdout_2026H1`: pass

So the theory can be treated as:

- `reference_line_pass`
- `promotion_gate_fail`

## Interpretation

This does **not** mean `v86` is adopted as the official promoted theory.

It means:

1. `v86` is the best practical frontier in the current ticket-shape branch.
2. Further comparisons may use `v86` as the operating baseline.
3. Any future improvement should be judged against `v86`, not against `v80`.

## Operational rule from here

Use `v86` as the active reference line when:

- comparing new no-new-data theory variants
- discussing practical race-level output shape
- checking whether a new branch is better than the current frontier

Do not describe `v86` as promoted unless the fixed gate itself is revised in advance.

## Status

- fixed gate: fail
- reference line: active
- current frontier: `v86`
