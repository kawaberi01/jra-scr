# v10 ratio-guard bridge iteration

Date: 2026-07-04

## Objective

Bridge the gap between:

- `v62`: validation no-max improved, train September broke
- `v63`: train looked strong, validation weakened

The base remained `v60`:

- race 1-8 only
- field size >= 14
- standard races buy only the top middle

## Candidates

- `v64`: axis <= 4.0 and first-middle odds ratio <= 2.0 => skip compressed 1-ticket shapes
- `v65`: axis <= 4.0 and first-middle odds ratio <= 2.5 => skip compressed 1-ticket shapes
- `v66`: axis <= 5.0 and first-middle odds ratio <= 2.0 => skip compressed 1-ticket shapes
- `v67`: axis <= 5.0 and first-middle odds ratio <= 2.5 => skip compressed 1-ticket shapes

## Results

Reference:

- `v60` train no-max: `1.0167 / 0.9453 / 1.0353`
- `v60` validation no-max: `0.9553`

Candidates:

| theory | wf1 no-max | wf2 no-max | wf3 no-max | validation no-max | note |
|---|---:|---:|---:|---:|---|
| v64 | 1.0167 | 0.9453 | 1.0353 | 0.9553 | identical to v60 |
| v65 | 1.0167 | 1.0254 | 0.7219 | 0.9939 | validation improves, Sep collapses |
| v66 | 1.0558 | 0.9305 | 1.0667 | 0.9350 | train mostly holds, validation worsens |
| v67 | 1.0558 | 1.0358 | 0.7452 | 1.0163 | first validation no-max > 1.0 here, but Sep collapses |

## Reading

1. `v64` changed nothing material. The tighter `<= 4.0 / <= 2.0` guard almost never fired.
2. `v65` and `v67` both improved validation by removing compressed 1-ticket shapes, but the same removal damaged September train badly.
3. `v66` preserved the train profile better than `v65`/`v67`, but validation stayed below the `v60` line.
4. This means simple ratio-guard boundary tuning around `v60` is now exhausted in the same way as the earlier odds-threshold sweep.

## Decision

Keep `v60` as the current frontier.

Do not adopt `v64`-`v67`.

## Next direction

The next useful change should not be another small ratio boundary tweak. The more promising next axis is:

- conditional second-stage filtering after `v60` selection using a context that is not purely price-shape
- or changing the middle ranking itself so the single retained ticket is different, instead of only skipping tickets after selection

