# v9 same-distance bucket iteration

Date: 2026-07-04

## Hypothesis
- `v55` still looked weak in some middle same-distance buckets.
- In particular, `middle_same_dist_top3_rate=0.15-0.25` was consistently poor.
- Test whether hard-rejecting those middles improves the remaining train floor without breaking validation.

## Tested theories
- `v57`: `v55` + reject `middle_same_dist=0.15-0.25`
- `v58`: `v55` + reject `middle_same_dist=0.15-0.25` and `missing`
- `v59`: `v55` + allow only `middle_same_dist in {0.25-0.35, ge_0.35}`

## Train walk-forward no-max ROI
- `v55`: Jul 0.6450 / Aug 0.8533 / Sep 0.8484
- `v57`: Jul 0.5585 / Aug 0.7357 / Sep 0.8484
- `v58`: Jul 0.6250 / Aug 0.7218 / Sep 0.8915
- `v59`: Jul 0.4581 / Aug 0.8106 / Sep 1.0343

## Validation (2025-10-01..2025-12-31)
- `v55`: ROI 1.3010 / no-max 1.1775
- `v57`: ROI 1.3363 / no-max 1.2066
- `v58`: ROI 1.2660 / no-max 1.1147
- `v59`: ROI 1.2304 / no-max 1.0255

## Decision
- Reject all three.
- Hard middle same-distance bucket filters improved parts of validation but damaged the train floor.
- `v55` remains the strongest branch among the targeted-guard family.

## Interpretation
- The remaining weakness is not a single obvious same-distance bucket.
- The no-new-data route is now near the limit of simple guard tightening.
- Next useful move is not another coarse filter. It is a smaller structural change inside `v55`, such as ticket-count logic or middle selection shape for the `race 1-8 / field_size>=14` subset.
