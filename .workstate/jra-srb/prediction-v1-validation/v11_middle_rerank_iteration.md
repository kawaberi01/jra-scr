# v11 middle rerank iteration

Date: 2026-07-05

## Objective

Keep the `v60` structure and change only which single middle candidate survives on standard races.

The two hypotheses were:

1. the large-field penalty for middle odds above 10.0 is too conservative
2. the `same_dist_top3_rate=0.25-0.35` bonus pushes the retained middle toward weak validation shapes

## Sweep

Baseline:

- `v60`

Candidates:

- `v68`: weaken `middle_large_field_odds_over_10_penalty` from `4.0` to `2.0`
- `v69`: remove `middle_large_field_odds_over_10_penalty`
- `v70`: `v68` plus remove `middle_same_dist_0_25_0_35_bonus`
- `v71`: `v68` plus reduce `middle_same_dist_ge_0_35_penalty` from `6.0` to `2.0`

## Results

| theory | validation no-max | wf1 no-max | wf2 no-max | wf3 no-max |
|---|---:|---:|---:|---:|
| v60 | 0.9553 | 1.0167 | 0.9453 | 1.0353 |
| v68 | 0.9553 | 1.0167 | 0.9453 | 1.0353 |
| v69 | 0.9553 | 1.0167 | 0.7984 | 1.0353 |
| v70 | 1.0350 | 0.8611 | 0.9453 | 1.0353 |
| v71 | 0.9544 | 0.8611 | 0.9453 | 1.0353 |

## Findings

1. `v68` did nothing. The weaker `>10.0` middle-odds penalty alone does not change the retained ticket.
2. `v69` made August worse without helping validation.
3. `v71` also failed. Simply softening the `ge_0_35` same-distance penalty is not useful here.
4. `v70` is the first rerank variant that pushed validation no-max above `1.0`.

## What changed in `v70`

Validation improved mainly because the retained ticket mix shifted toward better-performing middle shapes:

- `middle_same_dist_top3_rate=0_25_0_35` became weaker exposure: validation no-max `0.1810`
- `middle_same_dist_top3_rate=ge_0_35` became stronger exposure: validation no-max `1.1561`
- `middle_odds=15_20` stayed strong: validation no-max `1.4133`
- `middle_popularity=5` remained the healthiest large bucket: validation no-max `1.5038`

But July broke in a localized way:

- `wf1_2025_07`, `race_no=r01_05`: no-max `0.0968`
- `wf1_2025_07`, course `10`: no-max `0.0000`
- `wf1_2025_07`, `axis_odds=4_6`: no-max `0.0000`

So `v70` is not globally better. It is a useful clue, not a release candidate.

## Decision

Keep `v60` as the current frontier.

Do not adopt `v70` yet.

## Next direction

The most promising next move is no longer generic odds tuning.

The next search should be:

- conditional use of the `middle_same_dist_0_25_0_35_bonus`
- especially separating the July-weak `r01_05` / `axis_odds 4-6` type from the validation-improving cases

