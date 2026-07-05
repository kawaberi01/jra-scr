# v13 ticket shape filter iteration

Date: 2026-07-05

## Objective

Move from "buy the highest-scored middle" to "buy only ticket shapes that look stable".

The first target was a ticket-level shape filter found from train walk-forward + validation only.

## Shape diagnosis from `v75`

Train + validation bucket analysis suggested one stable weak shape:

- `middle_trainer_recent_top3_rate = 0.15-0.25`

Post-ticket filtering on `v75` records gave:

- wf1 no-max `1.3000`
- wf2 no-max `0.9891`
- wf3 no-max `1.1381`
- validation no-max `1.2182`

That was strong enough to test as a frozen ticket-shape rule.

## Variants tested

- `v78`: candidate-level exclusion of `middle_trainer_recent_top3_rate=0.15-0.25`
- `v79`: ticket-level exclusion of `middle_trainer_recent_top3_rate=0.15-0.25`
- `v80`: ticket-level filter `axis_popularity in {1,2}` and `middle_popularity in {4,5}`

## Results

### `v78`

Candidate-level exclusion changed reranking and degraded August:

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max |
|---|---:|---:|---:|---:|
| v78 | 1.2429 | 1.2366 | 0.8588 | 1.0615 |

Decision: reject before holdout.

### `v79`

Ticket-level filtering preserved the intended train + validation effect:

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max |
|---|---:|---:|---:|---:|
| v79 | 1.2182 | 1.3000 | 0.9891 | 1.1381 |

This was the first clean "ticket shape only" candidate worth freezing.

### `v80`

Ticket-level filtering with tighter popularity shape:

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max |
|---|---:|---:|---:|---:|
| v80 | 1.0342 | 1.4875 | 0.8097 | 1.6357 |

Holdout `2026-01-01..2026-06-28`:

- ROI: `1.0781`
- no-max ROI: `0.9658`
- verdict: reject

This is the closest holdout result so far in the ticket-shape line, but August train still breaks and no-max holdout stays below `1.0`.

### `v81` and `v82`

Two narrow follow-ups from `v80` were checked before holdout:

- `v81`: `v80` plus exclude `odds_ratio < 2`
- `v82`: `v80` plus exclude `middle_same_course_top3_rate < 0.15`

Results:

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max |
|---|---:|---:|---:|---:|
| v81 | 1.1559 | 1.5867 | 0.7800 | 1.7615 |
| v82 | 0.9889 | 1.3867 | 0.8074 | 1.7615 |

Decision:

- `v81`: reject before holdout
- `v82`: reject before holdout

Neither improved the August train weakness enough to justify a holdout run.

### `v83`, `v84`, and `v85`

Standalone micro-shape theories were then tested from the sweep:

- `v83`: `axis_popularity=1` and `middle_popularity=5`
- `v84`: `axis_popularity=2` and `middle_popularity=4`
- `v85`: only the two exact shapes above

Results:

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max | validation bets |
|---|---:|---:|---:|---:|---:|
| v83 | 1.2063 | 0.5429 | 0.0000 | 1.6143 | 16 |
| v84 | 0.0000 | 0.0000 | 0.5375 | 2.5500 | 6 |
| v85 | 0.8773 | 1.3556 | 0.5125 | 2.5444 | 22 |

Decision:

- `v83`: reject before holdout
- `v84`: reject before holdout
- `v85`: reject before holdout

Interpretation:

1. The good-looking holdout pockets from the sweep were real but too small.
2. Once evaluated as independent theories, the month-to-month variance was too high.
3. Exact popularity-shape products alone are not enough to satisfy the train + validation gate.

### `v86` and `v87`

After the standalone micro-shapes failed, a constrained `v80` follow-up sweep was run to find one- or two-condition ticket filters that preserve sample size.

The strongest pair rules were:

- `v86`: exclude `middle_jockey_recent_top3_rate = 0.15-0.25` and exclude `axis_odds = 4.0-6.0`
- `v87`: exclude `middle_jockey_recent_top3_rate = 0.15-0.25` and exclude `odds_ratio < 2`

Results:

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max | holdout no-max |
|---|---:|---:|---:|---:|---:|
| v86 | 1.4364 | 1.1200 | 0.9187 | 1.7800 | 1.2417 |
| v87 | 1.3739 | 1.1200 | 0.9187 | 1.6182 | 1.1686 |

Decision:

- `v86`: reject for promotion
- `v87`: reject for promotion

Interpretation:

1. This is the first branch after `v80` where validation and holdout both moved clearly above `1.0`.
2. The remaining blocker is concentrated in `wf2_2025_08`.
3. So the frontier has improved, but the fixed walk-forward gate is still not cleared.

### `v86` follow-up sweeps

`v86` was then treated as the active frontier and re-swept to isolate the remaining `wf2_2025_08` weakness.

Observed August weak pockets on `v86`:

- `race_no = r06_08`
- `middle_popularity = 5`
- `odds_ratio = ge_5`
- `middle_same_dist_top3_rate = ge_0_35`

Full single-filter and all-pair sweeps were run on top of `v86`.

Best rows:

| rule | train floor | validation | holdout |
|---|---:|---:|---:|
| `exclude_middle_odds=15_20 AND exclude_middle_trainer_recent_top3_rate=0.25-0.35` | 1.0286 | 0.5312 | 0.9529 |
| `exclude_middle_odds=15_20 AND exclude_middle_jockey_recent_top3_rate=0.25-0.35` | 1.0143 | 0.9000 | 0.7136 |
| `exclude_odds_ratio=lt_2 AND exclude_middle_trainer_recent_top3_rate=0.25-0.35` | 0.9714 | 0.9412 | 1.3860 |
| `exclude_axis_odds=4_6 AND exclude_odds_ratio=lt_2` | 0.9187 | 1.5048 | 1.2681 |

Decision:

- no `v86` follow-up candidate cleared the fixed train + validation gate

Interpretation:

1. There are pairs that repair August.
2. But every pair that repairs August enough breaks validation or holdout.
3. So the current `v80 -> v86` line now looks locally exhausted under the fixed gate.

## Holdout result for `v79`

Holdout `2026-01-01..2026-06-28`:

- ROI: `0.6191`
- no-max ROI: `0.5200`
- verdict: reject

So the rule is a validation-efficient shape filter, but not a durable holdout rule.

## Findings

1. Ticket-level shape filters are a valid search direction.
2. Candidate-level shape exclusion is not equivalent; reranking side effects matter.
3. A shape that looks strong across train + validation can still collapse on holdout.
4. The current feature space still lacks a durable separator for wide partner quality.

## Decision

Keep the direction:

- analyze ticket shape
- freeze ticket-level filters
- test them on holdout

But reject `v79` and `v80` themselves.

## Next direction

Do not return to score-weight tuning.

The next shape sweep should test combinations of:

- `middle_popularity`
- `odds_ratio`
- `axis_popularity`
- ticket-level `trainer_recent_top3_rate`
- ticket-level `same_course_top3_rate`

The focus remains:

- buy only ticket shapes that repeat on train + validation
