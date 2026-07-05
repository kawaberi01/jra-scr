# Custom Theory Sweep Report

Date: 2026-07-03

## Objective

Check whether small boundary changes around the current `v9` family can produce a theory that passes both:

- train walk-forward robustness (`2025-07` to `2025-09`)
- validation gate (`2025-10-01` to `2025-12-31`)

## Variants

- `s18_a15`: `middle_odds_max=18.0`, `axis_odds_max=15.0`
- `s19_a15`: `middle_odds_max=19.0`, `axis_odds_max=15.0`
- `s19_5_a15`: `middle_odds_max=19.5`, `axis_odds_max=15.0`
- `s20_a15`: `middle_odds_max=20.0`, `axis_odds_max=15.0` (`v9`)
- `s19_a10`: `middle_odds_max=19.0`, `axis_odds_max=10.0`
- `s19_5_a10`: `middle_odds_max=19.5`, `axis_odds_max=10.0`
- `s20_a10`: `middle_odds_max=20.0`, `axis_odds_max=10.0` (`v11`)

## Key Results

| theory | validation ROI | validation no-max ROI | wf1 Jul ROI | wf2 Aug ROI | wf3 Sep ROI |
|---|---:|---:|---:|---:|---:|
| s18_a15 | 0.9136 | 0.8710 | 0.9424 | 1.0303 | 0.7341 |
| s19_a15 | 1.0262 | 0.9854 | 0.8955 | 1.0178 | 0.7394 |
| s19_5_a15 | 1.0182 | 0.9787 | 0.9784 | 0.9932 | 0.6289 |
| s20_a15 | 1.0344 | 0.9959 | 0.9595 | 0.9521 | 0.6114 |
| s19_a10 | 1.0128 | 0.9829 | 0.8947 | 0.8334 | 0.7265 |
| s19_5_a10 | 1.0198 | 0.9906 | 0.9709 | 0.8121 | 0.6172 |
| s20_a10 | 1.0356 | 1.0072 | 0.9523 | 0.7808 | 0.6000 |

## Findings

1. `middle_odds_max=18.0` improves September train robustness, but validation breaks badly.
2. Restoring the boundary to `19.0` recovers validation headline ROI, but `no-max ROI` still stays below `1.0`.
3. Tightening `axis_odds_max` to `10.0` improves axis hit quality on validation, but train August and September weaken.
4. `19.5` is not a stable compromise. It degrades September materially without restoring validation enough.

## Why `s18_a15` failed validation

Compared with `v11` / `s20_a10`, `s18_a15` dropped profitable `2025Q4` races by over-filtering middle candidates. The main mechanism was:

- `v11` bet, `v12` skip: 49 races
- skipped winning races: 14
- lost payout total: 11,690 yen
- almost all were `insufficient_middle_candidates:1`

This means `middle_odds_max=18.0` is too strict for `2025Q4`.

## Decision

This sweep does not produce a release candidate.

Simple threshold tuning on:

- `middle_odds_max`
- `axis_odds_max`

is exhausted for the current `v9` family. The next iteration should change a different dimension of the decision rule.

## Recommended Next Hypothesis

Do not continue with more fine-grained odds thresholds first.

Next, test one of these instead:

- add a score-gap rule for the first middle candidate, not only the second
- add a race-shape rule using candidate score dispersion
- add a market-balance rule using axis odds plus second-choice odds ratio
- separate one-middle and two-middle races instead of a single `min_middles_to_bet` gate
