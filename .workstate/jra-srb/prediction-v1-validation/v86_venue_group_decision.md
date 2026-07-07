Date: 2026-07-06

# v86 Venue Group Decision

## Purpose

Evaluate whether `v86` should remain one all-venue theory or be handled by venue group.

## Groups

- `main`: Tokyo / Nakayama / Kyoto / Hanshin
- `local`: Sapporo / Hakodate / Fukushima / Niigata / Kokura
- `chukyo`: Chukyo

## Combined result

| group | tickets | hits | ROI | no-max ROI | no-top3 ROI |
|---|---:|---:|---:|---:|---:|
| `main` | 53 | 17 | 1.8170 | 1.6623 | 1.3792 |
| `local` | 42 | 15 | 1.6476 | 1.4357 | 1.1595 |
| `chukyo` | 11 | 1 | 0.5455 | 0.0000 | 0.0000 |

Source:

- `v86_venue_group_summary.json`
- `v86_venue_group_summary.md`

## Interpretation

The all-venue `v86` is masking a strong venue-group difference.

`main` is the strongest group:

- enough tickets to be useful as a first operating segment
- ROI remains positive even after removing the largest payout
- no-top3 ROI remains positive

`local` is positive in aggregate, but less stable:

- aggregate ROI is good
- holdout no-max ROI drops to `0.4636`
- several split-level no-top3 values collapse to `0.0`

`chukyo` is clearly weak:

- only 11 total tickets
- ROI below 1.0
- no-max ROI is `0.0`
- this explains why `v88 = v86 + skip Chukyo` improved numerically

## Decision

Do not keep `v86` as a fully uniform all-venue operating theory.

Handle it as:

- `v86_main`: usable reference branch
- `v86_local`: watch / limited confidence branch
- `v86_chukyo`: reject for betting, diagnostic only

## Adoption status

- `v86_main`: candidate for next formal evaluation
- `v86_local`: not rejected, but requires tighter split checks
- `v86_chukyo`: reject as an operating segment

## Next step

Formalize `v86_main` as the next candidate branch and rerun:

1. train walk-forward
2. validation
3. holdout

Then evaluate `v86_local` separately with stricter stability checks.

Do not create 10 venue-specific theories yet. The current sample size does not support that.
