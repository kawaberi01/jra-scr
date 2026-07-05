# Spec To Current Mapping

Date: 2026-07-04

Source spec:

- `docs/nakaana_self_learning_agent_spec.md`
- `docs/jra/12_予想エージェント評価プロトコル.md`

## 1. Status Summary

Current implementation should be understood as:

- strong on evaluation protocol and reproducible backtest artifacts
- partial on agent separation and theory-version workflow
- weak on full autonomous prediction-agent operation

In short:

- evaluation research loop: mostly implemented
- self-learning theory promotion loop: partially implemented
- production prediction agent: not yet implemented

## 2. Mapping Table

| Spec area | Current status | Current artifact / note |
|---|---|---|
| Goal = improve theory, not train LLM | Implemented | `goal_progress_snapshot.md`, fixed version comparisons |
| Result leakage prohibition | Implemented in evaluation protocol | `docs/jra/12_予想エージェント評価プロトコル.md`, evaluator uses pre-race-style features only |
| Prediction / Evaluator / Analyst / Validation separation | Partially implemented | evaluator and validation are concrete; analyst/revision are manual-script based, not separate runtime agents |
| Theory version freeze | Implemented | `evaluate_v1_validation.py` `THEORIES`, per-version reports, no in-place holdout retuning |
| Time-series split: train / validation / holdout | Implemented | train walk-forward + 2025Q4 validation + 2026H1 holdout |
| Holdout treated as final untouched check | Implemented | `v10` frozen holdout failure retained as evidence |
| Deterministic evaluator | Implemented | `evaluate_v1_validation.py` |
| JRA + netkeiba result/payout integration | Implemented | `analysis.sqlite`, netkeiba mapping/result/payout storage |
| odds_view usage | Partially implemented | supported as data source conceptually; current main evaluator does not yet depend on a persistent pre-race odds snapshot feature set |
| Exclusion reasons logged | Implemented | per-run `*_validation_races.json`, reports |
| Validation and holdout reports | Implemented | `*_validation_report.md`, `v10_holdout_report.md` |
| Theory comparison scoreboard | Implemented | `rule_space_scoreboard.md/json` |
| Analyst output | Partially implemented | analysis scripts and iteration memos exist, but not a single autonomous Analyst Agent |
| Rule Revision Agent | Partially implemented | candidate theories created manually via code edits and sweeps |
| Validation Agent | Implemented enough for research | explicit validation and holdout commands exist |
| Theory Registry | Partial | versions exist in code and artifacts, but no dedicated registry table / YAML registry workflow |
| `theory_v*.yaml` workflow | Not implemented | theories live in Python `THEORIES`, not external YAML |
| `save_prediction` / `predictions` storage | Not implemented in current evaluation line | current flow stores evaluated race outputs, not full prediction-agent JSON schema records |
| `save_evaluation` / structured evaluation store | Partial | JSON artifacts exist; no dedicated long-lived evaluation table workflow in current line |
| JSON schema validation for prediction output | Not implemented | because full Prediction Agent output schema is not yet active |
| Full Orchestrator Agent | Not implemented | orchestration is manual via scripts/commands |
| Full Prediction Agent using pre-race snapshot only | Not implemented | current theory evaluation reconstructs a deterministic rule scorer rather than running an LLM prediction agent |
| Guard Agent | Not implemented as runtime component | guardrails exist procedurally in protocol and review practice |
| Learning summary artifact | Partial | iteration docs exist, but no single canonical `learning_summary.md` per cycle |
| Full SQLite self-learning tables (`theory_versions`, `predictions`, `evaluations`) | Mostly not implemented in current prediction line | analysis DB exists; agent-lifecycle schema is incomplete from prediction-agent perspective |

## 3. What Already Works

These are already strong enough to support research:

- fixed evaluation windows
- race ID mapping and stored netkeiba results
- deterministic ticket evaluation
- train walk-forward reruns
- validation reruns
- holdout reruns
- per-version artifacts
- scoreboard and rejection memo

This means the project already has a usable evaluation lab.

## 4. What Is Missing To “Run The Agent”

There are two meanings of “run”.

### A. Run the research loop

Meaning:

- add a new theory
- evaluate on train and validation
- decide promote / reject / next test

Status:

- already possible today

Missing pieces:

- more disciplined theory registry
- less manual candidate generation
- cleaner summary artifact per iteration

### B. Run the real prediction agent

Meaning:

- ingest pre-race snapshot
- produce prediction JSON
- save prediction
- later join to result/payout
- score automatically
- update theory candidate lifecycle

Status:

- not complete

Missing pieces:

1. Externalized theory registry
   - move current `THEORIES` toward `theory_v*.yaml` or DB-backed version records

2. Pre-race snapshot contract
   - define and freeze one input JSON that contains only allowed pre-race fields

3. Prediction record schema
   - implement `predictions`, `prediction_tickets`, optional `theory_versions`

4. Prediction runner
   - deterministic or LLM-backed prediction generator that emits schema-valid JSON

5. Evaluation join runner
   - read saved predictions, fetch/join result+payout, store evaluation rows

6. Promotion workflow
   - codify `promote / reject / needs_more_test`

7. Operational batch
   - one command that runs collection -> prediction -> later evaluation -> summary

## 5. Remaining Steps

Recommended order:

1. Freeze the current evaluation lab as v1 research infrastructure
2. Implement a theory registry format
3. Implement prediction JSON schema and persistence
4. Implement a prediction runner over pre-race snapshot only
5. Implement evaluation persistence and summary generation
6. Add one new feature family and search for the next valid theory line
7. Only after a candidate exists, wire full promote/reject automation

## 6. Estimate

Assuming no major API redesign is needed and data access is stable:

### To run the research loop comfortably

- about 2 to 5 working days

Work includes:

- registry cleanup
- standard iteration summary
- command normalization

### To run the full prediction-agent pipeline end to end

- about 1 to 2 weeks

Work includes:

- prediction schema
- persistence tables
- prediction runner
- evaluation runner
- promote/reject lifecycle

### To reach the actual goal

Goal:

- a theory that survives train, validation, and holdout

Estimate:

- not schedule-safe yet

Best realistic estimate:

- if the next new feature family works quickly: 1 to 3 weeks
- if several failed theory lines are needed: 3 to 6+ weeks

The main uncertainty is not plumbing anymore. It is theory discovery.

## 7. Practical Conclusion

The project is not blocked on architecture.

It is at this state:

- infrastructure for evaluation: near-usable
- infrastructure for full autonomous agent operation: incomplete but straightforward
- probability bottleneck: theory quality, not data plumbing

So the next best move is:

- finish the minimal prediction-agent pipeline
- simultaneously start one truly new feature line

Do not spend another long cycle only on `v25` threshold variants.
