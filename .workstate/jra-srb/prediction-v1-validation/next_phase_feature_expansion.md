# Next-Phase Feature Expansion

Date: 2026-07-04

## Why move to a new feature space

`rule_space_scoreboard.md` and `current_rule_space_decision.md` now say the same thing:

- the current `v1/v2` rule space has `0` train+validation candidates
- `v10` is the only frozen holdout run and it failed
- the strongest validation rows are mostly `v25` derivatives, but every one of them still breaks at least one train split

So the bottleneck is no longer evaluation infrastructure. The bottleneck is theory space.

## What can be used now without API changes

The following are already in `analysis.sqlite` or can be derived from it.

### Already stored directly

- JRA `races` / `runners`
  - `race_date`
  - `course`
  - `race_no`
  - `surface`
  - `distance`
  - `horse_name`
  - `jockey`
  - `trainer`
  - `weight_carried`
- netkeiba `netkeiba_race_results`
  - `weather`
  - `track_condition` (partial only)
  - `surface`
  - `distance`
- netkeiba `netkeiba_result_entries`
  - `frame_no`
  - `win_odds`
  - `popularity`
  - `horse_weight`
  - `horse_weight_diff`

### Can be derived now

- field size / runner count
  - from `runners` grouped by `race_id`
- race timing bucket
  - from `race_no`
- same-course / same-surface / same-distance recent form
  - from JRA historical results already present
- jockey recent form
  - same DB, aggregated over recent windows
- trainer recent form
  - same DB, aggregated over recent windows
- target-race interaction features
  - examples: `course x distance`, `surface x distance`, `field_size x odds band`

These are the lowest-risk next features because they do not require more scraping or schema work.

## What is still missing or weak

### Historical-only proxy today

The current evaluation uses `netkeiba_result_entries.win_odds` and `popularity` as a stand-in for pre-race market data.

That is acceptable for offline comparison, but it is still a proxy. For production-grade promotion, the theory should eventually be checked with true pre-race snapshots.

### Weak or incomplete coverage

- `track_condition`
  - only partially available in `netkeiba_race_results`
- JRA `runners.card_odds`
  - effectively unavailable historically for train/validation
- JRA `runners.card_popularity`
  - effectively unavailable historically for train/validation

### Requires additional collection if we want it as a first-class feature

- true pre-race win odds snapshot
- true pre-race popularity snapshot
- richer market-shape features from odds snapshots
  - favorite strength
  - top-3 compression
  - axis-vs-middle ratio by timing
- broader odds board snapshots if we want to use market structure directly instead of final-result proxies

## Recommended iteration order

### Iteration A: no-API-change feature expansion

Add only features derivable from the current DB:

1. field size
2. jockey recent-form aggregates
3. trainer recent-form aggregates
4. same-course / same-surface / same-distance recent-form aggregates
5. race-no bucket or late-card feature

Target:

- produce `v3` theory space that is genuinely different from `v1/v2`
- evaluate on the same fixed train/validation protocol
- do not touch holdout until one candidate survives train+validation

### Iteration B: replace market proxies with true pre-race snapshots

If Iteration A still fails, the next most valuable change is to stop depending on result-page market proxies for the target race and move to stored pre-race snapshots.

Target:

- use real pre-race odds / popularity snapshots for target-race market features
- rerun the same train/validation protocol as a new version line

### Iteration C: market-shape features

Only after pre-race snapshots are stable:

1. favorite compression
2. rank gaps among top runners
3. timing-based odds movement features
4. optional wide-board shape features

This is the highest collection cost, so it should come after Iteration A and B.

## Recommended stop/go rule

Move a new theory to holdout only when all of the following are true:

- validation no-max ROI >= 1.00
- train walk-forward no-max ROI stays above a fixed floor in all three splits
- the theory is not carried by a single payout spike
- the feature set is available in production, not only in historical result pages

## Immediate practical instruction

The next efficient move is not more threshold tuning inside the current `v1/v2` branch.

The next efficient move is:

1. build derived features from the current DB
2. open a new theory line that uses those features
3. evaluate it with the existing train/validation framework
