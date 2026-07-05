# Holdout Data Audit

Period: 2026-01-01..2026-06-28

Audit command:

```powershell
rtk .venv-win\Scripts\python.exe .workstate\jra-srb\prediction-v1-validation\audit_holdout_data.py
```

Latest audit date: 2026-07-03

## Current DB State

JRA official data in `data/analysis.sqlite`:

| item | count |
|---|---:|
| races | 1338 |
| runner rows | 18896 |
| result rows | 18893 |
| min date | 2026-01-04 |
| max date | 2026-06-28 |

Monthly JRA coverage:

| month | races | runners | results |
|---|---:|---:|---:|
| 2026-01 | 276 | 3982 | 3982 |
| 2026-02 | 282 | 4021 | 4021 |
| 2026-03 | 300 | 4237 | 4237 |
| 2026-04 | 264 | 3743 | 3743 |
| 2026-05 | 144 | 2002 | 2002 |
| 2026-06 | 72 | 911 | 908 |

JRA join verification:

| item | count |
|---|---:|
| races | 1338 |
| runners | 18896 |
| race_results | 1338 |
| result_entries | 18896 |
| payouts | 16010 |
| races_with_runners | 1338 |
| missing_runner_races | 0 |

netkeiba supplemental data:

| item | count |
|---|---:|
| holdout races | 1338 |
| mapped races | 1338 |
| result parent races | 1338 |
| result entry races | 1338 |
| payout races | 1338 |

Audit gates:

| gate | status |
|---|---|
| jra_months_complete | true |
| missing_jra_months | - |
| netkeiba_mapping_complete | true |
| netkeiba_results_complete | true |
| netkeiba_payouts_complete | true |
| AUDIT_STATUS | PASS |

## Completion Notes

Completed补完:

- Created verified 2026-05 netkeiba meeting calendar.
- Saved 2026-05 netkeiba mappings to `netkeiba_race_mappings`: 144/144 mapped.
- Collected 2026-05 netkeiba `race_result`/payout data: 144/144 saved.
- Re-fetched JRA official result data for 2026-06-27 Kokura and filled missing `202606271010` result/payout rows.

2026-05 verified netkeiba calendar:

| course | meeting_no | start_date | start_day_no |
|---|---:|---|---:|
| niigata | 1 | 2026-05-02 | 1 |
| tokyo | 2 | 2026-05-02 | 3 |
| kyoto | 3 | 2026-05-02 | 3 |

## Judgment

Holdout data is ready for the frozen v10 holdout evaluation.

Do not change v10 after seeing holdout results.
