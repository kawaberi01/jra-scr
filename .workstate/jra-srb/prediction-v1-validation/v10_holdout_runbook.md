# v10 Holdout Runbook

Frozen theory: `v10`

Validation evidence:
- period: 2025-10-01..2025-12-31
- ROI: 108.50%
- ROI without max payout: 103.61%
- axis top3: 49.64%
- status: validation freeze candidate

## Freeze Rule

Do not change `v10` after seeing holdout results.

Allowed before holdout:
- Fill missing data.
- Verify mappings.
- Fix data ingestion bugs that affect both validation and holdout in the same way.
- Re-run validation to confirm `v10_validation_summary.json` is unchanged except for metadata.

Not allowed before or after holdout:
- Tune odds thresholds.
- Tune race-number threshold.
- Tune score weights.
- Add/remove ticket guards based on holdout performance.

## Required Pre-Holdout Audit

Run:

```powershell
rtk .venv-win\Scripts\python.exe .workstate\jra-srb\prediction-v1-validation\audit_holdout_data.py
```

Do not run holdout scoring until the audit proves:
- JRA official runners/results are present for the holdout races to be evaluated.
- netkeiba mappings are regenerated from verified netkeiba meeting numbers.
- netkeiba result entries and payouts are complete enough for unbiased scoring.

Current audit status is recorded in:

```text
.workstate/jra-srb/prediction-v1-validation/holdout_data_audit.md
```

## Holdout Command

Run this once after the audit passes:

```powershell
rtk .venv-win\Scripts\python.exe .workstate\jra-srb\prediction-v1-validation\evaluate_v1_validation.py `
  --theory-version v10 `
  --from-date 2026-01-01 `
  --to-date 2026-06-28 `
  --period-label holdout `
  --db data/analysis.sqlite `
  --output-dir .workstate/jra-srb/prediction-v1-validation `
  --cache-dir .workstate/jra-srb/prediction-v1-validation/netkeiba-cache `
  --offline
```

Expected output files:
- `v10_holdout_summary.json`
- `v10_holdout_races.json`
- `v10_holdout_report.md`

## Holdout Pass Criteria

Treat v10 as a release candidate only if holdout satisfies all of these:
- ROI >= 100%
- axis_top3_rate >= 45%
- ROI without max payout is not materially below 100%
- Exclusions are explainable by predeclared rules, not data defects.

If holdout fails, record the result as a true out-of-sample failure. Start a new iteration from validation/training data only; do not tune directly on holdout.
