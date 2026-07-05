# Holdout Data Collection Runbook

Target period: 2026-01-01..2026-06-28

Purpose:
- Fill the data required to run frozen `v10` on holdout.
- Avoid biased partial holdout scoring.
- Avoid uncontrolled large access bursts.

Do not change `v10` while running this runbook.

## Current Status

Latest audit shows:
- races: 1338
- JRA runner rows: 18896
- JRA result rows: 18893
- netkeiba mapped races: 1338
- netkeiba result/payout races: 1338
- audit status: PASS

The holdout data补完 is complete. Keep the commands below as the reproducible
procedure for re-audit or future backfill work.

Run the audit at any time:

```powershell
rtk .venv-win\Scripts\python.exe .workstate\jra-srb\prediction-v1-validation\audit_holdout_data.py
```

## Step 1: Fill JRA Official Data

Use month/course batches. Do not run the full half-year as one command.

Recommended first pass:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-analysis --from-date 2026-01-01 --to-date 2026-01-31 --courses nakayama,kyoto,kokura,tokyo --db data/analysis.sqlite --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 100 --skip-existing
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-analysis --from-date 2026-02-01 --to-date 2026-02-28 --courses tokyo,nakayama,kyoto,hanshin,kokura --db data/analysis.sqlite --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 100 --skip-existing
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-analysis --from-date 2026-03-01 --to-date 2026-03-31 --courses nakayama,chukyo,hanshin,kokura --db data/analysis.sqlite --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 100 --skip-existing
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-analysis --from-date 2026-04-01 --to-date 2026-04-30 --courses fukushima,tokyo,nakayama,kyoto,hanshin --db data/analysis.sqlite --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 100 --skip-existing
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-analysis --from-date 2026-05-01 --to-date 2026-05-31 --courses all --db data/analysis.sqlite --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 100 --skip-existing
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-analysis --from-date 2026-06-01 --to-date 2026-06-28 --courses hakodate,fukushima,kokura --db data/analysis.sqlite --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 100 --skip-existing
```

If a run ends with `collection_runs.status = partial`, run the same command again after checking the audit output. `--skip-existing` prevents saved card/result payloads from being fetched again.

After each month:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli verify-analysis-joins --from-date 2026-01-01 --to-date 2026-01-31 --db data/analysis.sqlite
```

If races exist but runners are missing, use the rate-limited backfill:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli backfill-analysis-runners --from-date 2026-01-01 --to-date 2026-01-31 --courses all --db data/analysis.sqlite --only-missing --min-interval-seconds 3 --limit 50
```

Repeat with `--limit 50` until dry-run shows no missing targets.

Dry-run:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli backfill-analysis-runners --from-date 2026-01-01 --to-date 2026-01-31 --courses all --db data/analysis.sqlite --only-missing --dry-run
```

## Step 2: Verify netkeiba Meeting Numbers

Do not trust generated 2026H1 mappings until the meeting calendar is verified against actual netkeiba pages.

Expected artifact:

```text
.workstate/jra-srb/prediction-v1-validation/netkeiba_meeting_calendar.2026_h1.verified.csv
```

CSV columns:

```csv
course,meeting_no,start_date,start_day_no
```

Use actual netkeiba `race_id` page titles/descriptions to confirm `meeting_no` and `day_no`.

## Step 3: Regenerate 2026H1 Mapping

After the verified calendar exists:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli generate-netkeiba-mapping `
  --from-date 2026-01-01 `
  --to-date 2026-06-28 `
  --db data/analysis.sqlite `
  --output .workstate/jra-srb/prediction-v1-validation/netkeiba_mapping.holdout_2026h1.verified.csv `
  --meeting-calendar-csv .workstate/jra-srb/prediction-v1-validation/netkeiba_meeting_calendar.2026_h1.verified.csv `
  --save-to-db
```

Do not proceed if `unmapped` is unexpectedly high.

## Step 4: Collect netkeiba Results

Use dry-run first:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-netkeiba-results `
  --from-date 2026-01-01 `
  --to-date 2026-06-28 `
  --db data/analysis.sqlite `
  --use-db-mapping `
  --dry-run
```

Then collect in bounded batches:

```powershell
rtk .venv-win\Scripts\python.exe -m jra_srb.cli collect-netkeiba-results `
  --from-date 2026-01-01 `
  --to-date 2026-06-28 `
  --db data/analysis.sqlite `
  --use-db-mapping `
  --max-live-requests 100 `
  --min-interval-seconds 3 `
  --retries 1
```

Repeat until dry-run reports `unsaved=0`.

## Step 5: Gate Before Holdout

Run:

```powershell
rtk .venv-win\Scripts\python.exe .workstate\jra-srb\prediction-v1-validation\audit_holdout_data.py
```

Proceed only when:

```text
AUDIT_STATUS=PASS
```

Then follow:

```text
.workstate/jra-srb/prediction-v1-validation/v10_holdout_runbook.md
```
