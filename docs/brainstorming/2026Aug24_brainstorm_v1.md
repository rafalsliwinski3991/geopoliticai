# Improving the repo cleanup plan (docs/plans/2026Aug24_plan_for_cleaning_repo_v2.md)

**Started:** 2026-08-24
**Status:** Complete
**Outcome:** `docs/plans/2026Aug24_plan_for_cleaning_repo_v3.md`

## Context verified against the codebase

- `extract_claims` output (`extracted_claims`) is genuinely dead — `cross_check_facts_agent` reads the four lane claim lists directly. Plan item 1 is correct.
- `build_graph(infosphere=..., report_mode=...)` validates both args but binds neither; a module-level `graph = build_graph()` already exists at `src/graph.py:165`. Plan item 2 is correct but smaller than it reads.
- The sync endpoint is `async def` but calls `run_pipeline` synchronously — it blocks the event loop today. Plan's `run_in_threadpool` fix is real.
- `ChatOpenAI` is constructed in `llm.py` with no `max_retries` override, so the LangChain/OpenAI SDK default (2 retries) is already active.
- `web_searcher` already issues one Brave request per allowed domain (~3/lane) plus a combined-query fallback; there are 5 lanes per run.
- `web_searcher` raises `ValueError` for a missing `BRAVE_SEARCH_KEY`; the sync endpoint maps `ValueError` -> HTTP 400, so a server misconfiguration is reported as a client error.
- `compose_final` uses TRUE-verdict claims only; `cross_check_facts` assigns MISLEADING to any claim it cannot match. Every documented failure path therefore converges on the canned "no TRUE claims" text.
- `referee.LOADED_TERMS` is English-only, so the loaded-language gate is inert in the Polish infosphere.
- No `recursion_limit` is set at compile time.
- `report_mode` is never plumbed from the API; requests always run "full".
- Environment: `uv` is not installed and `geo_venv` has no `langgraph`, so `make test` / `make lint` cannot run as written.
- `CLAUDE.md` is stale beyond topology: it claims nodes are bound via `functools.partial` in `build_graph()`; they actually read `RunnableConfig` via `nodes/runtime_config.py`.

## Settled decisions

- **Q1 — Scope boundary** — Option (c): pull `recursion_limit` into this pass; leave the Polish loaded-language gate out, as its own later pass. _(rationale: keeps the cleanup pass tight; the Polish referee gate is acknowledged as a real functional hole but is tracked separately rather than folded into a plan already covering four areas.)_
  - Follow-up to track separately: `referee.LOADED_TERMS` is English-only, so the loaded-language gate is inert for the default `polish` infosphere. Fix needs a language-keyed term table plus threading `language`/`RunnableConfig` into `run_referee_checks`, which currently takes neither.

## Design tree

- Improve plan v2 -> v3
  - **Scope boundary** — SETTLED, then partly reversed at Q11: `recursion_limit` is OUT (inert on an acyclic graph); the doc fix replacing it is IN; Polish referee gate deferred to its own pass
  - **Output-quality bottleneck** — SETTLED: out of scope; deferred as its own follow-up
    - Streaming UX — SETTLED: draft styled as explicitly provisional (frontend-only)
    - Degraded-run visibility — SETTLED: coverage line instead of an error-count note; §3.3 error plumbing retained
  - **Resilience design** — SETTLED: explicit `max_retries` on `ChatOpenAI`; no hand-rolled LLM retry; search retry confined to the combined-query fallback; keep `LLMInvocationError` / `SearchExhaustedError` boundaries and node fallbacks
    - Token-limit escalation — SETTLED: removed entirely in favour of a single ceiling
      - Ceiling value — SETTLED: 16384, matching the removed loop's final tier
    - `max_retries` value — SETTLED: 2, explicit, no behavior change; tail-bound documented as a known
  - **Verification gate** — SETTLED: whole "Landing order and completion gate" section removed; per-step "Tests and acceptance" retained; no env-setup step
  - **API error taxonomy** — SETTLED: no 400 branch; single sanitized 500 path for non-Pydantic failures

## Current frontier (open questions)

_Empty. Every branch visited._

One item carried into the plan as an explicit open flag rather than a settled decision: **Q16** was not answered; plan v3 §5.3 applies the docs-only fix and marks it for the user's override.

## Round log

### Round 1
**Q1 — Scope boundary.** Asked whether to keep the plan's exclusion of the Polish loaded-language gate and `recursion_limit`, add both, or add `recursion_limit` only.
Recommended (b) both. **User answered (c)**: `recursion_limit` only; Polish gate becomes its own pass.

### Round 2
**Q2 — TRUE-only synthesis bottleneck.** Asked whether step 4's streaming work is worth it given that `MISLEADING` is overloaded and most failure paths converge on the canned "no TRUE claims" string.
Recommended (b) a step 0 relaxing the gate. **User answered (a)**: leave it, out of scope. Streaming stays as planned.

### Round 3
**Q3 — Retry layering.** Asked whether to keep the plan's hand-rolled retries, given `ChatOpenAI` already defaults to `max_retries=2` and `web_searcher` already probes each domain separately plus a combined fallback (worst case ~60 Brave calls/run against a 1 req/s free tier).
Recommended (b). **User answered (b)**: explicit `max_retries`, no wrapper; search retry only on the combined-query fallback; keep the boundary exceptions and fallbacks.

### Round 4
**Q4 — Verification gate.** Asked whether to add an explicit "step 0: establish a runnable environment", given `uv` is absent and `geo_venv` lacks `langgraph`, making the plan's own completion gate unrunnable.
Recommended (a). **User answered**: they don't want a "Before merging" section in the plan at all. Reshapes rather than answers the env question — follow-on posed as Q5.

### Round 5
**Q5 — What survives the cut.** Asked whether the landing order and an environment prerequisite survive the removal of the "Before merging" checklist.
Recommended (b). **User answered (c)**: drop the whole section, landing order included; no environment step.

### Round 6
**Q6 — API error taxonomy.** Enumerated all nine `raise ValueError` sites in `src/` and showed that none reachable by the sync endpoint's handler are actually caller faults.
Recommended (c) after enumeration. **User answered (c)**: drop the 400 branch entirely.

### Round 7
**Q7 — Streaming draft presentation.** Showed that the streamed synthesis is torn apart and redistributed by `supervisor_step`, so the user watches text arrive and then be replaced by a differently-shaped document (worst in `compact` mode, where most of it is truncated away).
Recommended (b). **User answered (b)**: style the draft as provisional.

### Round 8
**Q8 — Degraded-run visibility.** Showed that plan §3.4's "N pipeline stages degraded" note uses implementation vocabulary, that `len(errors)` is an error count rather than a stage count (one node can append two records), that it would fire on routine partial-search failures, and that it is blind to zero-results-without-exception lanes.
Recommended (d). **User answered (d)**: coverage line in the existing fact-check summary.

### Round 9
**Q9 — `llm.py` escalation loop.** Showed the escalation triggers on English substring matching against exception text, that its `for…else` branch is unreachable, and that it interacts with the newly-explicit `max_retries`.
Recommended (b) harden detection. **User answered (d)**: remove the escalation entirely.

### Round 10
**Q10 — Output-token ceiling.** With escalation removed, asked what single ceiling replaces it, noting truncation is now unrecoverable.
Recommended (a). **User answered (a)**: 16384.

### Round 11
**Q11 — `recursion_limit`.** Verified against the LangGraph docs that `recursion_limit` is a top-level runtime config key, not a `compile()` parameter, and that the project's own `CLAUDE.md`/`AGENTS.md` instruct the wrong form in ten places. Also established the graph is acyclic at a fixed 8 supersteps, making the parameter unreachable.
Recommended (c) add-plus-fix, noting (d) was more consistent. **User answered (d)**: fix the docs, skip the parameter.

### Round 12
**Q12 — Documentation scope.** Found that `CLAUDE.md` carries three claims that are false independent of this pass (`from agents import`, the `llm.py` Responses-API description, and `functools.partial` node binding), all in sections the pass already rewrites, and that `AGENTS.md` already contains correct wording for two of them.
Recommended (b). **User answered (b)**: fix the false claims in the touched sections; decline full reconciliation.

### Round 13
**Q13 — `report_mode` exposure.** Established the parameter is CLI-live (default `compact`) and HTTP-absent (default `full`), and that `_normalize_report_mode` is duplicated across `graph.py` and `supervisor.py`.
Recommended (b). **User answered (b)**: keep it CLI-only; collapse the duplicated validator.

### Round 14
**Q14 — `max_retries` value.** Worked out that the worst-case retry budget (~13.3 min) exceeds the frontend's 10-minute hard abort at the inherited default.
Recommended (b) `max_retries=1`. **User answered (a)**: keep 2, explicit. Tail bound recorded as a documented known rather than a fix.

### Round 15
**Q15 — `checkpointer` parameter.** Showed that step 2 preserves a parameter no caller passes and a `run_pipeline` conditional whose second branch can never execute, for a capability the plan explicitly declines to build.
Recommended (c) keep on `build_graph`, drop from `run_pipeline`. **User answered (b)**: drop it from both.

### Round 16
**Q16 — `OPENAI_MODEL` inert.** Showed the env var is documented as a tuning knob but cannot reach any pipeline node, because every call site passes an `agent_key` present in `AGENT_MODEL_NAMES`.
Recommended (d) docs-only. **Not answered** — user closed the session here. Applied as (d), flagged as open in plan v3.

### Close
User declared the brainstorm complete and asked for a fixed plan (v3) with detailed code changes. Written to `docs/plans/2026Aug24_plan_for_cleaning_repo_v3.md`.

Implementation detail discovered while writing the plan, which would have broken the Q13 decision as stated during the interview: `_normalize_report_mode` **cannot** be consolidated into `graph.py`. `graph.py` does `from nodes import (...)`, so `nodes/supervisor.py` importing from `graph.py` would be circular. It goes in `models.py`, which both already import and which already owns `normalize_language`.
