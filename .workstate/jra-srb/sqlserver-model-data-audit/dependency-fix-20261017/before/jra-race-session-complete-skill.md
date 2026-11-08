---
name: jra-race-session-complete
description: Run persistent JRA race sessions from pre-race prediction through official result storage and evaluation. Use whenever a user wants a JRA prediction saved before post time, later asks to confirm or evaluate the result, or manages multiple JRA races in the same thread with predictions, results, payouts, and evaluations stored in analysis SQLite.
---

# JRA Race Session Complete

Use `jra-race-predictor` for the prediction itself. This skill adds mandatory pre-race persistence, per-race session tracking, official result storage, and evaluation.

Before the first local API call in each prediction or result workflow, run [local-race-api-ready](../local-race-api-ready/SKILL.md). Skip a repeated check when readiness was already confirmed in the same workflow. If readiness fails, do not call the dependent API.

## Invariants

- Save and read back the final user-facing prediction before returning it.
- Do not fetch the result before the prediction has been saved successfully.
- Treat `(race_id, prediction_id)` as the session key. Never identify a race by race number alone when multiple courses or dates are possible.
- Store only information available at prediction time in `pre_race_snapshot`.
- Store the exact displayed ranking, marks, axis, opponents, decision status, and tickets in `prediction_json`.
- Store tickets only when the governing `jra-race-predictor` rules permit them. Formal V89-derived tickets are allowed for Tokyo, Nakayama, Kyoto, and Hanshin during the provisional operation period, but `v89_provisional_rank_v1` is ranking-only and must save no V89-derived tickets. V90-derived tickets are formal tickets for Sapporo, Hakodate, Fukushima, Niigata, and Kokura. Preserve any raw API `shadow`/`not_final`/`shadow_only`/`rejected_for_purchase` status separately as an implementation or validation status.
- Preserve `result_entries.rank IS NULL` records in the result DB, but exclude them from finish-rank model inputs.
- Never relabel a post-time reconstruction as a newly saved pre-race prediction.

## Phase 1: Predict and save

1. Resolve date, course, race number, meeting number/day, and `race_id`.
2. Follow `jra-race-predictor` to fetch the prediction bundle, comparison, betting decision, and required combination odds.
3. Confirm the race has not started. Do not call a result endpoint in this phase.
4. Freeze the final response content before saving:
   - `prediction_id`: `jra-{race_id}-session-{prediction_as_of_compact}`
   - `theory_version`: identify the predictor and mode
   - `mode`, `budget`, `created_at`
   - complete pre-race bundle or an auditable snapshot with timestamps and component status
   - displayed ranking and `predicted_top3`
   - `head_horse_numbers`, `axis_horse_numbers`, `opponent_horse_numbers`
   - betting-decision status and ticket policy
   - for V90 official sessions, `betting_decision_status=v90_official`, the API's `raw_betting_decision_status`, and `strategy=v90_official`
   - `prediction_tickets`, including only the single budget plan selected for evaluation
5. Save with `scripts/save_jra_prediction_to_analysis_sqlite.py`.
6. Read back `GET /jra/predictions/{prediction_id}` and verify the ranking, tickets, race ID, and pre-race timestamp.
7. Only after successful read-back, return the prediction and include `prediction_id` plus `予想保存済み`.

If saving fails, report `予想未保存` explicitly, do not fetch results, and keep the exact payload available for retry.

## Multiple races in one thread

Keep a compact ledger in the conversation and verify it against the DB when resuming:

| race_id | date/course/R | prediction_id | prediction | result | evaluation |
| --- | --- | --- | --- | --- | --- |

Use these states: `saved`, `pending`, `finalized`, `evaluated`, `failed`.

- Add one row immediately after each prediction save.
- Do not overwrite another race's row when a new race is predicted.
- For “9Rの結果”, use the unique recent matching session only when date and course are unambiguous. Otherwise ask which course/date.
- If thread context is compressed or uncertain, query `GET /jra/predictions?race_id=...` or list predictions by date before acting.
- If multiple predictions exist for one race, use the `prediction_id` recorded in the thread. Ask before evaluating when it cannot be determined.

## Phase 2: Store result and evaluate

1. Resolve the exact ledger row and confirm its saved prediction through `GET /jra/predictions/{prediction_id}`.
2. Fetch the official JRA result without inventing missing fields.
3. Require at least one result entry and one payout. Otherwise report `未確定` and stop without evaluation.
4. Save with:

   `POST /jra/meetings/{date}/{course}/races/{race_no}/result/save`

5. Verify `race_results`, `result_entries`, and `payouts` for the exact `race_id`.
6. Evaluate with `scripts/evaluate_saved_prediction_to_analysis_sqlite.py` or:

   `POST /jra/predictions/{prediction_id}/evaluate`

7. Read back `GET /jra/evaluations/{evaluation_id}` and verify:
   - predicted versus actual top three
   - winner hit and top-three-box hit
   - axis in top three
   - stored ticket results, stake, payout, and return rate
8. Report saved counts and both IDs, then mark the ledger row `evaluated`.

## Evaluation rules

- Evaluate only the tickets stored before the race.
- Treat stored `v90_official` tickets as formal purchases for deterministic payout evaluation, even when the raw API betting decision was `shadow_only`.
- Keep prediction accuracy separate from betting performance.
- With no stored tickets, report `未購入（投資0円）`; do not describe `hit=false` as a betting loss.
- Do not add a winning combination after the result.
- A top-five or marked-horse coverage observation may be reported, but it must not replace the deterministic `predicted_top3` metrics.
- If the original prediction was created in conversation but was not saved before post time, save it only as an explicitly labeled reconstruction and never mix it with compliant pre-race sessions. Set `generated_before_result=false`, `reconstruction_after_result=true`, and `reconstruction_label=結果判明後の復元予想` in `prediction_json`.

## Commands

Save a prediction payload:

```powershell
rtk uv run --project "D:\develop\jra-scr" python -X utf8 "C:\Users\main\skills\jra-race-session-complete\scripts\save_jra_prediction_to_analysis_sqlite.py" --input ".\tmp\jra_prediction_payload.json"
```

Evaluate a saved prediction after the official result is stored:

```powershell
rtk uv run --project "D:\develop\jra-scr" python -X utf8 "C:\Users\main\skills\jra-race-session-complete\scripts\evaluate_saved_prediction_to_analysis_sqlite.py" --input ".\tmp\jra_evaluation_payload.json"
```

Both scripts accept UTF-8 JSON on standard input when `--input` is omitted. Remove temporary payloads after verification.

## Minimal payloads

Prediction:

```json
{
  "prediction_id": "jra-202607181008-session-20260718T044411Z",
  "race_id": "202607181008",
  "theory_version": "jra-race-predictor:integrated_betting:session:v1",
  "mode": "integrated_betting",
  "budget": 1000,
  "created_at": "2026-07-18T04:44:11+00:00",
  "pre_race_snapshot": {},
  "prediction_json": {
    "predicted_ranking": [],
    "predicted_top3": [],
    "axis_horse_numbers": [],
    "generated_before_result": true
  },
  "prediction_tickets": []
}
```

Evaluation:

```json
{
  "prediction_id": "jra-202607181008-session-20260718T044411Z",
  "evaluation_id": "eval-jra-202607181008-session-20260718T044411Z",
  "review": {},
  "review_notes": []
}
```
