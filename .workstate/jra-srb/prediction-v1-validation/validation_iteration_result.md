# Validation Iteration Result

Period: 2025-10-01..2025-12-31

Data state:
- candidate races: 840
- evaluated races: 550
- excluded races: 290
- live requests during evaluation: 0
- remaining exclusions are rule exclusions such as few_candidates, not missing netkeiba result/payout data.

## Versions

| version | hypothesis | ROI | axis top3 | wide hit | tickets | payout | decision |
|---|---|---:|---:|---:|---:|---:|---|
| v1 | Baseline history score, middle odds 8..30, max 2 wide tickets | 90.41% | 43.82% | 10.30% | 1019 | 92130 | baseline only |
| v2 | Reduce recent-top3 volatility and penalize poor recent average rank more | 90.69% | 43.45% | 10.30% | 1019 | 92410 | reject: axis quality got worse |
| v3 | Keep v1 score, but prefer an axis with win odds <= 15.0 | 95.04% | 49.64% | 11.12% | 1025 | 97420 | promoted parent for ticket tests |
| v4 | Keep v3 axis guard, but narrow middle odds to 8..20 | 100.65% | 49.64% | 12.83% | 912 | 91790 | keep as current candidate |
| v5 | Keep v3 axis guard, but narrow middle odds to 8..18 | 94.14% | 49.64% | 12.34% | 867 | 81620 | reject: narrowed too far |
| v6 | Keep v4 rules, but buy only the top middle candidate | 96.36% | 49.64% | 11.93% | 503 | 48470 | reject: second ticket still carries value |
| v7 | Keep v4 rules, but require second middle axis-score gap > 10 | 100.73% | 49.64% | 12.90% | 907 | 91360 | improved, but v8 is better |
| v8 | Keep v4 rules, but require second middle axis-score gap > 5 | 100.87% | 49.64% | 12.86% | 910 | 91790 | promoted parent for confidence tests |
| v9 | Keep v8 rules, but bet only when two middle candidates are available | 103.44% | 49.64% | 12.90% | 814 | 84200 | improved, but v10 is better |
| v10 | Keep v9 rules, but bet only race 7 or later | 108.50% | 49.64% | 12.50% | 640 | 69440 | validation freeze candidate |

## Judgment

v10 is the current best validation candidate because it clears both primary validation targets and improves robustness:
- ROI >= 100%
- axis_top3_rate >= 45%
- return_rate_without_max_payout >= 100%

It is not a release candidate yet. It is a validation freeze candidate that must pass holdout after the holdout data is audited. Monthly validation split:
- 2025-10: ROI 117.60%, axis_top3 53.41%
- 2025-11: ROI 108.35%, axis_top3 48.79%
- 2025-12: ROI 99.12%, axis_top3 46.71%

The theory should now be frozen before holdout. Do not tune using holdout results.

## Holdout Result

Holdout period: 2026-01-01..2026-06-28

- ROI: 85.95%
- ROI without max payout: 82.00%
- axis_top3_rate: 51.58%
- decision: reject_release_candidate

v10 failed holdout. The axis rule remained stable enough, but the ticket rule did not sustain ROI out of sample.

Do not change v10 using this holdout result. Treat this as a true out-of-sample failure.

## Next Iteration

Start a new version line from train/validation data only.

Immediate blocker:
- train period 2025-01-01..2025-09-30 has JRA official data for 2615 races, but netkeiba result/payout coverage is only 48 races in 2025-08.
- That means train-period walk-forward validation cannot be trusted yet.

Next gates:
- Fill netkeiba mappings, results, and payouts for 2025-01-01..2025-09-30.
- Add train-period walk-forward splits, for example:
  - WF1: train through 2025-06-30, validate 2025-07-01..2025-07-31
  - WF2: train through 2025-07-31, validate 2025-08-01..2025-08-31
  - WF3: train through 2025-08-31, validate 2025-09-01..2025-09-30
- Compare new hypotheses on those walk-forward splits and on the existing 2025Q4 validation.
- Freeze the next candidate only after it is stable across train walk-forward and 2025Q4 validation.
- Run a fresh holdout only after the next candidate is frozen.

Supporting audits:
- holdout status: `.workstate/jra-srb/prediction-v1-validation/holdout_data_audit.md`
- train netkeiba status: `.workstate/jra-srb/prediction-v1-validation/audit_train_period_netkeiba.py`
