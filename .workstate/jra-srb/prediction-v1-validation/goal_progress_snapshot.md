# Goal Progress Snapshot

Date: 2026-07-05

## Goal

Establish a JRA prediction-agent theory that avoids overfitting, survives fixed train/validation/holdout evaluation, and can be rerun with stable artifacts and decision criteria.

## What is complete

- fixed evaluation periods exist
  - train: `2025-01-05..2025-09-30`
  - validation: `2025-10-01..2025-12-31`
  - holdout: `2026-01-01..2026-06-28`
- train walk-forward evaluation exists and is rerunnable
- validation evaluation exists and is rerunnable
- holdout evaluation exists and is rerunnable
- netkeiba mapping / result storage in `analysis.sqlite` is in place
- current rule-space results are aggregated in:
  - `rule_space_scoreboard.md`
  - `rule_space_scoreboard.json`
- current rejection logic is documented in:
  - `current_rule_space_decision.md`
- additional feature/rule iterations through `v42` are documented in:
  - `v3_derived_feature_iteration.md`
  - `v4_shape_context_iteration.md`
- ticket-context and shape-context diagnostics now exist:
  - `ticket_context_v25.md`
  - `ticket_shape_context_v25.md`
  - `ticket_shape_filter_search_v25.md`

## What is not complete

- there is still no theory that survives:
  - train walk-forward
  - validation
  - final holdout confirmation
- current `v1/v2/v25-derived` rule space is exhausted for promotion through `v42`
- the `v60 -> v75` rerank line improved validation but still failed holdout
- production-grade target-race market features still rely too much on historical result-page proxies

## Current decision

At this point the project should be treated as:

- evaluation framework: usable
- current rule space: rejected for promotion
- current candidate count: 0 of 81 theories
- next required work: change the ticket theory shape, not more local threshold tuning

Recent rejected additions:

- `v35..v38`: middle jockey/trainer/course hard filters
- `v39..v41`: field-size and first-gap race-shape filters
- `v42`: dirt-only plus strict axis odds <= 2.5
- `v75`: conditional rerank line, validation no-max `1.0350` but holdout no-max `0.6497`
- `v79`: ticket-shape filter line, validation no-max `1.2182` but holdout no-max `0.5200`
- `v80`: ticket-shape popularity line, holdout ROI `1.0781` but holdout no-max `0.9658`
- `v83..v85`: standalone micro-shape line, small pockets existed but Aug/validation collapsed with too few bets
- `v86..v87`: constrained `v80` pair-filter line, validation and holdout both > 1.0, but `wf2_2025_08` stopped at `0.9187`
- `v86` all-pair follow-up sweep: no additional pair cleared train+validation; the remaining line looks locally exhausted
- `v86` is now documented as the active `reference line` despite fixed-gate failure
- `v88`: `v86 + skip Chukyo` clears train/validation/holdout numerically, but is rejected for adoption because the added rule is a full-venue exclusion with high overfit risk

These improved isolated pockets, but none passed train and validation together.

## Reference-line status

- active reference line: `v86`
- reason:
  - `wf1_2025_07 = 1.1200`
  - `wf3_2025_09 = 1.7800`
  - `validation_2025Q4 = 1.4364`
  - `holdout_2026H1 = 1.2417`
  - only `wf2_2025_08 = 0.9187` blocks fixed promotion
- reference memo:
  - `v86_reference_line_decision.md`

## Tracked diagnostic branch

- tracked branch: `v88`
- branch memo:
  - `v88_skip_chukyo_decision.md`
  - `v88_formal_adoption_decision.md`
- current handling:
  - numeric pass
  - formal adoption reject
  - diagnostic comparison branch only

## Current venue-group branch

- current branch: `v89`
- branch meaning:
  - `v86` base logic
  - apply only to main venues: Tokyo / Nakayama / Kyoto / Hanshin
- branch memo:
  - `v86_venue_group_decision.md`
  - `v89_main_venue_decision.md`
- current handling:
  - better structured than `v88`
  - next operating candidate
  - not final adoption because train walk-forward coverage is incomplete

## Current working direction

The next theory line should be explored under this fixed rule:

- do not optimize by minor score-weight tuning
- do not respond to holdout by patching thresholds
- instead, buy only ticket shapes that are repeatedly stable in train + validation

In practice this means:

1. separate `axis quality` from `wide partner selection`
2. analyze hit/miss distributions by ticket shape
3. build explicit buy/skip rules for stable shapes
4. evaluate those shape rules only on train walk-forward + validation before any new holdout run

## Exit condition for the overall goal

The thread goal should be considered achieved only after all of the following are true:

1. a new theory line survives fixed train walk-forward and validation
2. that theory is frozen and run once on holdout
3. holdout result is acceptable by the documented gate
4. the feature inputs are reproducible for production operation
5. the final theory, evaluation commands, and decision memo are all stored as rerunnable artifacts
