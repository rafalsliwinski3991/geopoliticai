# Review: 2026Sep11_plan_eval-case-kinds_v1

**Source plan:** `docs/plans/2026Sep11_plan_eval-case-kinds_v1.md`
**Design context:** `docs/brainstorming/2026Sep11_brainstorm_v1_eval-cases-per-agent.md`
**Tier:** standard (preserved)
**Focus:** thorough review within the existing scope
**Branch / commit:** `2026Sep10-evals-for-reporter` / `52d54de`
**Uncommitted, relevant:** `app/tests/manual_quality/basic_agent_evaluation.py` is
modified in the working tree; so are four `app/src/agents/...` node files and
several guidance files. The plan is not yet implemented.
**Implementation status:** not started.
**Reviewed plan:** `docs/plans/2026Sep11_plan_eval-case-kinds_v2.md`
**Completion:** Complete. Every issue in the queue was discussed and answered.
**Readiness:** Ready for implementation
**User approval:** Awaiting approval

## Goal and constraints

Reorganize the advisory manual-quality eval suite from six flat cases tagged with
an `agent` field into four kinds, one case each, with the runner moving to one
dataset and one experiment per kind, the four rubric prompts extracted to a
sibling module, and three evaluator builders collapsed into one judge table. The
suite is advisory, gates no merge, and is reachable in CI only through the
dispatch-only `evals.yml` workflow. No application code under `app/src/` changes.

## Verified facts

- `arize-phoenix-client` 3.3.0, `arize-phoenix-evals` 3.6.0, `langgraph` 1.0.1,
  `langgraph-checkpoint` 3.0.1.
- The plan's deviation rationale is correct. In
  `phoenix/client/resources/experiments/__init__.py`, `run_experiment` forwards
  its own `retries` and `timeout` verbatim into its internal
  `evaluate_experiment` call. Keeping two calls is the only way to hold
  `retries=0` on the task and `retries=3` on the judges.
- `tests/manual_quality/` is not on `sys.path`. Only `app/src` is, via
  `__editable__.agent-0.0.1.pth`. Confirmed empirically. CI runs the runner as a
  script (`evals.yml:36`), which is why a flat sibling import works there and
  would fail under the unit test's `spec_from_file_location` loader.
- `OrchestratorState.destination` is a plain overwrite channel with no reducer
  (`app/src/agents/orchestrator/state.py`). After a multi-turn run, the state
  holds only the last turn's destination.
- `classify` always returns both `destination` and `standalone_query`
  (`app/src/agents/orchestrator/nodes/classify.py:68-71`), including on the
  `other` and `report` branches.
- The orchestrator's `reporter` node appends exactly one `AIMessage` on every
  path, refusal included (`app/src/agents/orchestrator/nodes/reporter.py`). So
  `messages[:-1]` is the thread as it stood before this turn's answer.
- `build_transcript` is exported from `agents.reporter` and budgeted by
  `MAX_TRANSCRIPT_CHARS = 400_000`.
- `build_initial_orchestrator_state(query)` already normalizes whitespace and
  raises on an empty query (`orchestrator/state.py`).
- Today's guards `validate_evaluations` (`basic_agent_evaluation.py:465`) and the
  task-run check (`:556`) are both hardcoded to exactly one case, as the plan
  states.

## Review coverage

| Area | Status |
| --- | --- |
| Goal and scope | reviewed |
| Architecture and boundaries | reviewed |
| Interfaces and data flow | reviewed |
| Failure and recovery | reviewed |
| Tests and evidence | reviewed |
| Cost and operation | reviewed |
| Delivery and maintenance | reviewed |
| User-facing UX | not applicable — the suite has no UI surface |

## Decisions

| ID | Question | Status | Outcome |
| --- | --- | --- | --- |
| D1 | Does `e2e` assert anything about turn one's routing? | accepted | B. Each scripted turn carries its expected destination and `run_e2e` raises on a mismatch, matching how `run_reporter_thread` already raises on a turn that did not pause. |
| D2 | Does the expectation cover every query turn or only the setup turns? | accepted | Setup turns only. A non-final `query` turn carries `expect` and `run_e2e` raises on a mismatch; the final turn stays graded by `route_correct`. |
| D3 | Keep the multi-case machinery in Task 5, or bake in one case per kind? | accepted | A. Fix the counters now. Guards count against `len(kind_cases)`, the task-run check loops, and a two-case regression test ships. |
| D4 | Prompt extraction forces a `sys.path` mutation in the test loader | accepted | As planned. Verified empirically; the one-line insert belongs in the test loader, not in the runner. |
| D5 | Does `report` keep `route_correct`? (plan's own open question) | accepted | Dropped, as the plan proposed. `route_correct` survives only where a zero is reachable: `orchestrator`, and the final turn of `e2e`. |

### D5 detail

`run_report` raises unless the turn paused, and the orchestrator's only
`interrupt()` is the reporter subgraph's gate. Pausing therefore implies
`destination == "report"`, and also implies the thread carried researched
material, which routing alone does not. The guard is strictly stronger than the
judge, so `route_correct` on that kind can only score one or never run at all.

Contrast with `e2e` under D2, where the final turn is deliberately not guarded
inside the task, so a zero is reachable and the judge stays.

### D1 detail

`OrchestratorState.destination` has no reducer, so the state after a multi-turn
run holds only the last turn's routing. As planned, a turn-one misroute in the
`e2e` finland case would leave every judge green. Option C, returning a
`destinations` list and comparing lists in `route_correct`, was explained on
request and rejected: it pushes a one-element list into the two single-turn
kinds' case files and reports a failure without naming the turn.

Accepted cost: on a misroute the task errors, so Phoenix records no scores at all
for that kind rather than a zero `route_correct` beside the other judges.

Noted for implementation: a resume turn does not re-run `classify`, so only
`query` turns carry an expectation.

## Corrections folded in without a vote

- `run_e2e` should build its turn input with
  `build_initial_orchestrator_state(query)` rather than hand-writing the
  non-empty-string check and `HumanMessage(query)`. `run_expert` already uses the
  matching `build_initial_pipeline_state`, and the helper normalizes whitespace
  too. Reuse before writing.
- Task 5 does not state the new `experiment_name` or the new `case_count` value
  in `experiment_metadata`. Both need specifying.

### D2 detail

Turn one's expectation lives in the input script and is a precondition checked
inside the task. The final turn's expectation lives in the output reference block
and is a graded score. The asymmetry is deliberate: setup turns exist to put
cited research into the thread, and a setup turn on the wrong branch is a broken
fixture, while the final turn is the subject under test and its routing is a
result. `run_reporter_thread` already draws this line by raising when a turn
never paused instead of scoring it as a poor report.

Implementation consequences: the turn-shape check widens from exactly `query` or
`resume` to also allow `query` with `expect`; resume turns never carry `expect`.
`cases.json` will show one turn with `expect` and one without, which needs a
comment at the turn validation so it does not read as an omission.

### D3 detail

Both shape guards count against one today and are correct only because a Phoenix
dataset currently holds one example. Once datasets are keyed by kind, a second
case in any kind makes `create_dataset` upload two examples, `run_experiment`
produce two task runs and twice the evaluation runs, and both guards raise after
the live spending has happened, with a message that reads like a graph failure.
The rejected alternative was a loader assertion of one case per kind, which would
walk back commit 45ef329's deliberate move to a shape allowing several cases per
agent.

Accepted cost: the multiplication and the loop have no caller today, and a
dozen-line regression test ships for a shape nothing currently uses. The test is
cheap because the existing module handle `_load_runner()` is typed `Any`, so
`mypy --strict` does not inspect the stub passed to `validate_evaluations`.

## Additional verified flags

- **`e2e` cannot run `groundedness`.** The orchestrator's `expert` node discards
  the expert's sources and returns only an `AIMessage`
  (`app/src/agents/orchestrator/nodes/expert.py`), and `OrchestratorState` has no
  key for them. Surfacing them would be an application-code change, which this
  plan puts out of scope. After `expert-taiwan-strait-v1` is deleted, the whole
  suite's citation-grounding signal rests on the niger case, which has only ever
  passed.

## Current unanswered question

None.

## Discussion log

### Round 1
Established the facts above. Opened with D1. **User chose B.**

### Round 2
Surfaced D1's consequence as D2. **User chose setup-only.**

### Round 3
Verified that `e2e` cannot run `groundedness` without an application-code change
and recorded it as a flag rather than reopening scope. Raised D3.

### Round 4
User asked repeatedly for D2 and then D3 to be re-explained, and for the eval
script's execution flow and vocabulary. Explained both in full with worked
walkthroughs; no new decision emerged. **User chose A on D3.**

### Round 5
Reported D4 as verified and sound with no decision needed, then raised D5, the
plan's own unasked question. Explained it with the `run_report` pause guard and
a table of what `route_correct` could record on each branch. **User answered
that `route_correct` belongs only in `e2e` or `orchestrator`**, which is the
plan's proposal, so the drop stands.

### Round 6
Wrote `docs/plans/2026Sep11_plan_eval-case-kinds_v2.md`. Queue empty.
