# Review: 2026Sep15_plan_orchestrator-general-eval_v1

- **Source plan:** `docs/plans/2026Sep15_plan_orchestrator-general-eval_v1.md`
- **Design context:** chat brainstorm 2026-09-15 (Q1A, Q2A, Q3B, Q4A) — no file.
- **Tier:** lightweight (kept).
- **Focus:** thorough review within existing scope.
- **Branch / commit:** `2026Sep10-evals-for-reporter` @ `c31e5a2`.
- **Uncommitted changes:** old runner, `cases.json`, `judge_prompts.py` deleted;
  `*_old.py` copies and `dataset.json` untracked; unit test modified but still
  references deleted `cases.json` / `judge_prompts.py` (currently broken).
- **Status:** Review complete; v2 approved (2026-09-15).

## Goal and constraints

Replace the 788-line multi-group runner with a small script: run the
orchestrator on each `dataset.json` example, score with one 1–5 LLM judge on
Phoenix or AX, advisory (exit 0).

## Verified facts

- Installed: `arize-phoenix-client` 3.3.0, `arize-phoenix-evals` 3.6.0,
  `arize` 8.52.1, `langchain-core` 0.3.83, `langgraph` 1.0.1.
- `AsyncClient.experiments.run_experiment(..., retries=...)` forwards the same
  `retries` to `evaluate_experiment` when `evaluators` is given
  (`phoenix/client/resources/experiments/__init__.py` ~2818–2828). So
  `retries=0` also removes judge retries.
- Old runner separated them on purpose: task `retries=0`, judge via
  `evaluate_experiment` with default 3 (old file lines 646–674); AX judge had a
  3-attempt loop (`JUDGE_RETRIES`).
- `dataset.json`: list with one entry, `agent_name="orchestrator"`, one example
  (`name`, `input.messages` in LangChain dict form, `output` with `messages`,
  `destination="other"`, `standalone_query`).
- `build_runtime_config`, `graph` exist in `agents/orchestrator/graph.py`;
  config symbols exist in `config.py`.
- Old prompt used single-brace `{placeholders}`; plan matches that style.
- `.github/workflows/evals.yml` currently triggers on `pull_request`
  (`workflow_dispatch` commented out, commit `52d54de` "tmp change"). CLAUDE.md
  says "dispatch-only". Pre-existing mismatch; plan's claim that CLAUDE.md stays
  true is not accurate today.
- Plan text nits: `ORCHESTRAOR_QUALITY_PROMPT` typo and mis-indented lines.

## Coverage

| Area | Status |
| --- | --- |
| Goal and scope | reviewed |
| UX / DX | reviewed (D3, logging) |
| Architecture | reviewed |
| Interfaces / data flow | reviewed (task output, judge mapping, dataset shape) |
| Failure and recovery | reviewed (D1, D3) |
| Tests | reviewed (D4) |
| Cost and operation | reviewed (D1 task retries=0; D2 deferred to follow-up) |
| Delivery | reviewed (lightweight, three ordered steps) |

## Decisions

- **D1 — Judge retries on Phoenix (and AX).** Status: accepted.
  Outcome: Phoenix uses `run_experiment(evaluators=None, retries=0)` then
  `evaluate_experiment(evaluators=[judge])` with default retries; AX `ax_judge`
  keeps a 3-attempt loop (`JUDGE_RETRIES = 3`) before returning `judge_error`.
  Rationale: `run_experiment` forwards `retries` to evaluators; a free-tier 429
  should not become a gap, and a failed task must not re-spend credit.
  Affects: step 2 constants, Phoenix and AX bullets.
- **D2 — `evals.yml` trigger vs CLAUDE.md.** Status: accepted (out of scope).
  Outcome: leave `evals.yml` and CLAUDE.md unchanged. The new plan stops
  claiming CLAUDE.md is fully accurate and lists the `pull_request` vs
  "dispatch-only" mismatch under follow-up. Accepted risk: the live eval keeps
  spending credit on every PR push until resolved separately.
  Affects: non-goals, required follow-up.

- **D3 — Orchestrator task failure.** Status: accepted.
  Outcome: after judging, log every failed task run (Phoenix
  `task_runs[*]["error"]`, AX result `error` column) and `raise SystemExit(1)`
  if any failed. Judge errors stay log-only (Q3B). Rationale: a broken app must
  not look green; Q3B only made the score advisory. Accepted risk: flaky
  Brave/OpenAI turns the PR check red while `evals.yml` runs on PRs (D2).
  Affects: step 2 `main`, Validation.
- **D4 — Tests for D1/D3 branches vs Q4A single test.** Status: accepted.
  Outcome: keep Q4A's single unit test; add manual Validation run with
  `OPENAI_API_KEY=invalid` expecting exit 1. (Reviewer corrected own suggestion
  from `BRAVE_SEARCH_KEY`: the only example routes to `chat`, which never calls
  Brave.) Accepted risk: no automated regression check for D1/D3.

Verified for D3: Phoenix catches task exceptions into `task_run["error"]`; AX
`arize/experiments/functions.py` catches them into the result `error` column.
`init_environment` uses `load_dotenv` default `override=False`, so a shell
override works for the manual check.

## Noted, not changed

- Judge sees full serialized messages incl. random ids and `response_metadata`
  (Q2A settled what the judge sees; prompt names fields to compare).
- Typo/indentation fixes applied in v2 as verified corrections.

## Result

- Reviewed plan: `docs/plans/2026Sep15_plan_orchestrator-general-eval_v2.md`
- Readiness: Ready for implementation
- User approval: Approved (2026-09-15)

## Current question

None. Next command: `/rs-implement-plan docs/plans/2026Sep15_plan_orchestrator-general-eval_v2.md`.

## Superseded notes

- Phoenix task errors are not logged (plan logs only evaluation errors).
- Judge sees full serialized messages incl. random ids/metadata (noise).
- Typo/indentation fixes in plan code block.

## Discussion log

- 2026-09-15: review started; D1 raised.
- D1 answer: "Separate judge retries (Recommended)". D2 raised.
- D2 answer: "Out of scope". D3 raised after verifying task-error handling.
- D3 answer: "Exit 1 on task failure (Recommended)". D4 raised.
- D4 answer: "Manual check only (Recommended)".
- v2 plan written; awaiting approval.
- Approval answer: "Approve v2".
