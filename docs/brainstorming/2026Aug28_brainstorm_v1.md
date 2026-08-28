# Simplifying the codebase: unnecessary abstractions, over-designed error classes, LangGraph practice

**Started:** 2026-08-28
**Status:** Complete
**Mode:** single (one question per round)

## Target design

One branch, one pass, ordered commits: mechanical deletions first, the streaming rewrite last, tests rewritten in the same pass.

**Kept, deliberately.** Every multi-agent seam: the `agents/<name>/` layout, shared modules never importing an agent, `SourcePolicy`, the `LLMSettings` default-plus-override chain including `ANSWER_LLM_SETTINGS`, `RetrievalSettings`, and the three `graph.py` build helpers. Also kept: the in-process rate limiter, both pieces of defensive code in `search.py`, and `init_tracing()` at module scope in `graph.py`.

**Deleted.** `cli.py` entirely. The sync endpoint `/api/run_pipeline`, and with it `run_pipeline`, `RunPipelineResponse`, the `BackgroundTasks` path, and the sync error mapping. `_sanitize_output`. The whole location feature, including `_resolve_location`, the `httpx` import in `database.py`, and the `location` column (dropped in `init_pool`). `log_output` and the two-phase write. `_ERROR_STATUS` and `_status_for`. The `astream_events` machinery: `_chunk_text`'s current home, `seen_nodes`, `PipelineEvent`, and the event-name string matching. The two `api.py` env parsers and their four module constants.

**Rewritten.** `graph.py` becomes construction only, ending near 25 lines. The streaming loop moves to `api.py` and follows the reference template's shape: `graph.astream(..., stream_mode="messages")`, filtering on `isinstance(message, (AIMessage, AIMessageChunk))`, yielding plain strings, with `_chunk_text` kept beside it for content blocks. Progress is inferred in `api.py`: the search label before the run starts, the answer label on the first token. Errors become one hierarchy under `PipelineError` with `status` on each class, `LLMInvocationError` included. `database.py` writes one row after a successful run and stays silent on failure.

## Context verified

Read `app/src/**` in full (~900 lines of application code, excluding tests and `.venv`).

- **Sizes:** `search.py` 237, `api.py` 256, `database.py` 97, `graph.py` 98, `config.py` 65, `models.py` 47, `llm.py` 47, `tracing.py` 43, `answer.py` 44, `search_and_fetch.py` ~35, `state.py` ~25, `expert/config.py` ~30.
- **Versions installed:** langgraph 1.0.1, langchain-core 0.3.83, langchain-openai 0.3.35, fastapi 0.135.1, trafilatura 2.2.0.
- **Error classes: four.** `PipelineError` (base, never raised directly), `SearchUnavailableError`, `NoSourcesError` in `models.py`, plus `LLMInvocationError` in `llm.py` outside that hierarchy. Every catch site (`api.py`) catches `(PipelineError, LLMInvocationError)` together, then re-splits them through an `_ERROR_STATUS` tuple table into 422/503/502.
- **`ANSWER_LLM_SETTINGS` in `agents/expert/config.py` is field-for-field identical to `DEFAULT_LLM_SETTINGS`** (gpt-4o-mini, 0.0, 60.0s, 16384). The whole per-agent override mechanism currently overrides nothing.
- **`SourcePolicy` (6 fields) parameterizes `search.py` so it "names no agent"** — it has exactly one instance, `EXPERT_SOURCES`, and one caller.
- **`RetrievalSettings`** is a frozen dataclass of two ints with one instance, `RETRIEVAL`.
- **Streaming is done twice.** The `answer` node accumulates chunks and writes `state["answer"]`; `astream_pipeline` separately reassembles the same tokens from `astream_events(version="v2")`; `run_pipeline` then re-joins those tokens and never reads `state["answer"]`. `_chunk_text` in `graph.py` re-implements content-block flattening that `llm.astream_text` already does.
- **`astream_events(version="v2")` is the older streaming API** for langgraph 1.0; `graph.astream(..., stream_mode=["updates", "messages"])` is the current idiom and would delete `_chunk_text` and the metadata sniffing.
- **The sync endpoint is unused by the frontend.** `frontend/index.html:428` calls only `/api/run_pipeline/stream`. `/api/run_pipeline` is exercised by unit tests and by nothing else in-repo.
- **`api.py` carries hand-rolled infrastructure:** in-process rate limiter with a module-level dict/deque/`threading.Lock`, `_read_positive_int_env`, `_parse_allowed_origins`, `_sanitize_output` (a UTF-8 encode/decode round-trip that is a no-op for any str already produced by the model), `_resolve_client_id`.
- **`database.py` swallows every exception** and calls the third-party `ip-api.com` inside the request path before the first DB insert.
- **Small indirections:** `build_runtime_config`, `build_initial_pipeline_state`, `build_graph` (called once, at import), `NODE_LABELS` re-exported through `agents/expert/__init__.py`.

## Design tree

- **Root: how far does simplification go** — SETTLED: more agents coming, so keep the multi-agent seams; simplify only agent-count-independent ceremony.
  - `SourcePolicy` / shared-boundary generality — PRUNED (kept; justified by the coming agents)
  - `LLMSettings` override chain and `RetrievalSettings` — SETTLED (both kept)
  - Error-class collapse — SETTLED (hierarchy + status attribute)
  - Streaming path — SETTLED (reference-template shape, `stream_mode="messages"`)
    - Progress signal location — SETTLED (inferred in `api.py`)
    - Layering: orchestration leaves `graph.py` — SETTLED
      - CLI as second consumer — SETTLED (deleted)
      - Runner module — MOOT once `run_pipeline` lost every consumer
  - Tracing init location — SETTLED (stays in `graph.py`, six options assessed)
  - Sync endpoint — SETTLED (deleted)
  - `api.py` hand-rolled infra — SETTLED (sanitize and env parsers go, limiter stays)
  - `database.py` — SETTLED (single insert, successes only, location removed, column dropped, failures silent)
  - `search.py` defensive code — SETTLED (both kept)
  - `graph.py` build helpers — SETTLED (all three kept)
  - Execution strategy — SETTLED (one branch, one pass)
  - Is LangGraph earning its place — PRUNED: `langgraph.json`, Studio, the Phoenix integration, and the reference template all assume it. No answer changes the work.

## Settled decisions

- **More agents are coming in the near future** — the multi-agent structure serves a real plan, not a hypothetical one. _(rationale: user states other agents are planned soon)_
  - Challenged on: "near future" with no named agent is the same bet that produced `ANSWER_LLM_SETTINGS` as a copy of the defaults → held by non-answer; the user moved on without naming one. Recorded as a stated intention, and carried as a flag rather than as evidence.
  - Consequences: `agents/<name>/` layout, the no-agent-imports rule, `SourcePolicy`, and the `LLMSettings` override chain all STAY. Simplification targets only ceremony that no number of agents would use: duplicate streaming, the error split, unused endpoints, hand-rolled `api.py` infra.

- **Error classes: option 2, one hierarchy with the status on the class** — `LLMInvocationError` moves into `models.py` under `PipelineError`; each class carries a `status` attribute; `_ERROR_STATUS` and `_status_for` are deleted and both endpoints catch `PipelineError` alone. _(rationale: distinct types stay useful as agents multiply, but the lookup table can drift out of sync with the class list and the one-line raise cannot)_
  - Challenged on: an HTTP status on a domain exception is a delivery-layer concern living in shared models, meaningless to the CLI and to LangGraph Studio → pending reply.
  - Consequences: deletes ~15 lines from `api.py`, removes the split `except (PipelineError, LLMInvocationError)`, makes `llm.py` import its error rather than define it. Import direction holds: `models.py` imports nothing local.

- **Streaming: adopt the reference template's shape** — `astream_pipeline` becomes a plain `AsyncIterator[str]` driven by `graph.astream(..., stream_mode="messages")`, filtering on `isinstance(message, (AIMessage, AIMessageChunk))`; the endpoint owns every SSE frame. _(rationale: user pointed at wassim249/fastapi-langgraph-agent-production-ready-template as the target shape)_
  - Reversal of an earlier lean: `_chunk_text` is KEPT (the template has the same helper as `extract_text_content`), moved next to the stream loop. Content blocks are a real case the moment a model returns them.
  - Not copied from the template: its `HTTPException(500)` for every failure (the typed 422/503/502 hierarchy is better and the frontend distinguishes them), and its absence of progress events (the frontend renders a progress log at `frontend/index.html:334`).
- **Layering: `graph.py` holds graph construction only** — state wiring, nodes, compile, export `graph`. Run/stream orchestration moves to the delivery layer. _(rationale: user's stated architectural principle)_
  - Challenged on: `cli.py` also consumes `run_pipeline`, so "the API layer owns running" would either duplicate the run loop or make the CLI import the web module → pending reply.
  - Consequences: picks Q5 option 1 by implication (progress inferred in `api.py`). `PipelineEvent`, the tuple union, `NODE_LABELS` as a graph export, and `run_pipeline` all leave `graph.py`.

- **Tracing stays in `graph.py`, with a comment** — option 1 of six assessed. `init_tracing()` remains at module scope, commented to say that `langgraph dev` loads this module and nothing else, so it is Studio's only hook. _(rationale: the construction-only rule exists to keep run/stream orchestration out of the module; one idempotent tracing call is not orchestration, and the alternatives cost a second ASGI app or a redirect module)_
  - Challenged on: `.env` sets `PHOENIX_COLLECTOR_ENDPOINT`, so the import-time call is not a no-op in any process that loaded it → accepted as a known cost.
  - Rejected: option 2 (lose Studio traces), option 3 (`studio.py` redirect module, breaks silently if `langgraph.json` is re-pointed), option 4 (package `__init__`, widest trigger surface), option 5 (`http.app` lifespan hook, correct but heavy), option 6 (lazy init in `llm.py`, loses traces for runs that die before the model).
  - Revisit trigger: the day a second agent adds a second graph module to `langgraph.json`, option 5 becomes right rather than heavy.

- **Delete `cli.py` entirely** — the API becomes the only entrypoint. _(rationale: user's call; nothing operational references it)_
  - Challenged on: a 3-line CLI calling `graph.ainvoke` would remove the second-consumer problem without losing the only stack-free way to run a real query → held; user did not revise.
  - Consequences: `CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md` all need editing. The `--log-level` flag disappears with it.
- **Delete the sync endpoint `/api/run_pipeline`** — SSE becomes the only way to run the pipeline over HTTP. _(rationale: only unit tests call it; the frontend uses the stream endpoint)_
  - Challenged on: a plain JSON endpoint is the easiest thing to hand a cron job, another service, or curl, and deleting a public route is a one-way door for callers outside this repo → held.
  - Consequences: deletes `RunPipelineResponse`, the `BackgroundTasks` import and its logging path, one rate-limit call site, and the sync error mapping. With `cli.py` also gone, `run_pipeline` has no consumers and deletes itself, which makes the runner-module question (Q7) moot: the streaming loop lives in `api.py`.
  - **Combined consequence, flagged:** after both deletions there is no non-SSE way to invoke the pipeline at all. Debugging means a browser or an SSE client. `/api/health` remains for uptime checks.

- **`api.py` infra: option 2** — delete `_sanitize_output` outright; collapse `_read_positive_int_env`, `_parse_allowed_origins`, and their four module constants into declared settings; keep the in-process rate limiter as-is. _(rationale: user's call)_
  - Challenged on: `CLAUDE.md` says config is hardcoded dataclasses, not env-parsed getters, and `pydantic-settings` is not installed (only `pydantic` 2.12.5 is), so option 2 as I framed it both adds a dependency and contradicts the repo's own config rule → pending reply. Counter-proposal: hardcode the CORS origins and rate-limit numbers the way `LLMSettings` is hardcoded, deleting both parsers with no new dependency.
  - Verified: neither `docker-compose.yml` nor `docker-compose.override.yml` sets `CORS_ALLOW_ORIGINS` or the rate-limit variables, so nothing in the repo currently overrides the defaults.
  - Known cost accepted: the rate limiter stays per-process and its client dictionary still grows without eviction.

- **Remove the location feature from the whole app** — `_resolve_location`, its `httpx` use in `database.py`, the `location` argument on the insert, and the three tests that patch it all go. _(rationale: user's call)_
  - Challenged on: whether the `location` column is dropped or left null, since dropping discards whatever rows already hold → pending reply.
  - Verified: `location` appears only in `database.py` (schema, resolver, insert) and `test_database.py` (three patch sites). The matches in `search.py` and `test_fetch.py` are the HTTP redirect header, unrelated.
  - Consequences: removes a plaintext third-party HTTP call from the request path, its 3-second timeout, and an undeclared dependency on a service rate-limited well below the app's own limit.

- **`database.py`: one insert at the end, successful runs only (option 3)** — `log_run(prompt, ip, output)` called after the stream completes; no error-path call. _(rationale: user's call)_
  - Challenged on: failed runs vanish, and `NoSourcesError` failures are the highest-signal rows in the table — they name the queries the allow-list cannot serve, which is what tells you which domains to add → pending reply.
  - Consequences: deletes `log_output`, the `log_id` plumbing, every `log_id is not None` check in `api.py`, and the awaited round-trip at the front of each request. `database.py` lands near 50 lines.
  - Still unanswered: whether a failed write gets a first-failure log line instead of vanishing silently.

- **Keep both config objects (option 3)** — `ANSWER_LLM_SETTINGS` and `RetrievalSettings` stay as the seams a second agent will use. _(rationale: user's call)_
  - Challenged on: `ANSWER_LLM_SETTINGS` must be kept manually equal to `DEFAULT_LLM_SETTINGS` and drifts invisibly, since nothing fails when the default changes and the copy does not → pending reply. Mitigation available: a one-line comment saying it is a deliberate explicit copy.

- **Keep the defensive code in `search.py` (option 3)** — the domain-dropping loop in `build_batch_query` and the `_extract_sync`/`_extract_text` pair both stay. _(rationale: user's call)_
  - Challenged on: the extraction pair has no argument in its favour at all, and the loop is unreachable, untested, and would run for the first time in production on a path that silently narrows source coverage → pending reply. Mitigation available: a test asserting every batch fits the Brave budget, which makes the loop's guarantee explicit and cheap.

- **Keep all three `graph.py` helpers (option 3)** — `build_graph`, `build_runtime_config`, `build_initial_pipeline_state` stay as the agent's construction surface. _(rationale: user's call)_
  - Challenged on: no caller has ever passed `thread_id`, so the validation branch is unreachable and the function's return value is a constant; the first caller to pass one exercises an untested path → pending reply.

- **Execution: one branch, one pass (option 1)** — every settled change plus the test rewrite land together. _(rationale: user's call; matches the Aug 25 rewrite that worked)_
  - Challenged on: a single diff mixes five mechanical deletions with the one genuinely risky change (the streaming rewrite), so a later bisect cannot separate them → pending reply. Mitigation available: ordered commits inside the one branch, deletions first, streaming last.
  - Test impact counted: 7 tests delete (3 for `log_output`, 1 for location, 2 for the sync endpoint, 1 more in `test_database.py`), 4 rewrite (`test_stream_logs_output_before_result`, the two execution tests in `test_expert_graph.py`, and the progress assertions).

- **`database.py` leftovers: option 4** — the `location` column is dropped in `init_pool`, and failed writes stay silent with no logger in the module. _(rationale: user's call)_
  - Challenged on: with no log line, a dead database is indistinguishable from an empty one, and the failure surfaces only as a table that stopped growing → held.

## Current frontier (open questions)

Empty. Every branch was visited or explicitly pruned.

## Carried as flags, not decisions

- **Ordered commits inside the single branch** — deletions first, streaming rewrite last, so a later bisect can separate the risky change from the mechanical ones. Raised as a challenge, not separately confirmed.
- **The rate limiter is per-process and its client dictionary never evicts.** Accepted knowingly. `_resolve_client_id` trusts the first `x-forwarded-for` value, so rotating headers grow the dictionary without bound. Revisit if the app ever runs more than one worker.
- **`ANSWER_LLM_SETTINGS` drifts invisibly from `DEFAULT_LLM_SETTINGS`.** Nothing fails if the default changes and the copy does not. A comment marking it a deliberate explicit copy was offered and not adopted.
- **`build_runtime_config` validates a `thread_id` no caller passes.** The first caller to pass one runs an untested branch. Kept for future checkpointing.
- **`build_batch_query`'s domain-dropping loop is unreachable** with the current policy, so it is untested and would first execute in production. A test asserting every batch fits the Brave budget was offered and not adopted.
- **Failed runs are no longer recorded anywhere.** `NoSourcesError` queries name the gaps in the allow-list, and after this change they exist only in container logs.
- **Import-time tracing** fires in any process that loaded `.env`, tests included. The `http.app` lifespan hook in `langgraph.json` is the scouted escape hatch if it becomes a nuisance.
- **After deleting both `cli.py` and the sync endpoint, no non-SSE way to run the pipeline remains.** Debugging means a browser or an SSE client.
- **"Other agents are coming in the near future"** — stated, not evidenced; no agent named when asked. Resolves the day a second agent's name and scope exist. Until then, treat every shared abstraction added "for the next agent" as unpaid-for.

## Round log

### Round 1 — Q1: Is a second agent actually coming?
Asked whether the multi-agent structure is serving a real near-term plan or a hypothetical one.
Lean was "treat it as no second agent, collapse the seams." **User answered:** other agents are coming in the near future. **Pushed back on** the absence of a named concrete agent, given that the one existing override point is a verbatim copy of the default → reply pending.

### Round 2 — Q2: Error classes
Asked whether to collapse four exception classes into one hierarchy with the HTTP status attached to the class.
Lean was option 2. **User answered:** option 2. **Pushed back on** HTTP codes living on domain objects → reply pending.

### Round 3 — Q4: The streaming path
Asked whether to replace `astream_events(version="v2")` with langgraph 1.0 stream modes plus an explicit progress writer.
Lean was option 1. **User answered:** pointed at the wassim249 FastAPI/LangGraph template, then stated the principle that `graph.py` should hold only graph construction and the API layer should own streaming. **Pushed back on** the CLI's dependency direction → reply pending.

### Round 4 — Q6: Does `init_tracing()` stay in graph.py?
Asked whether the construction-only rule admits the tracing call that exists solely because `langgraph dev` imports this module.
Lean moved from option 5 to option 1 after assessing all six. **User answered:** option 1. **Pushed back on** the import-time side effect with a live endpoint in `.env` → accepted as a known cost, with option 5 scouted as the escape hatch.

### Round 5 — Q7: CLI direct, or a runner module?
Asked where the run loop lives now that orchestration is leaving `graph.py`.
Lean was option 3 (keep a streaming runner, delete `run_pipeline`). **User answered:** delete `cli.py` entirely. **Pushed back on** the fact that deleting the tool is not required to get the benefit — a 3-line CLI calling `graph.ainvoke` also removes the second-consumer problem → reply pending.

Verified while asking: no Makefile target, Dockerfile entrypoint, compose command, or test references `cli.py`. It is named in `CLAUDE.md:34`, `AGENTS.md:14/19/48/88`, and two files under `docs/plans/`, so deleting it means editing all three guidance files per the repo's own rule.

### Round 6 — Q8: The sync endpoint
Asked whether `/api/run_pipeline` survives, given the frontend never calls it.
Lean was delete. **User answered:** delete. **Pushed back on** the combined effect with the CLI deletion → recorded as a flagged consequence rather than a blocker.

### Round 7 — Q9: The hand-rolled infrastructure in api.py
Asked which of the four home-grown helpers earn their place.
Lean was option 2. **User answered:** option 2. **Pushed back on** the contradiction with the repo's hardcoded-config rule and the missing dependency → reply pending.

### Round 8 — Q10: database.py
Asked about silent failure and the third-party geolocation call sitting in the request path.
Lean was option 4 (single insert at the end). **User answered:** remove the location feature from the entire app. **Pushed back on** the fate of the existing column and its data → reply pending. The two-phase-versus-single-insert half of the question is still open.

### Round 9 — Q11: database.py shape
Asked whether removing location also collapses the insert-then-update pair into one write.
Lean was option 1 (with an error-path call). **User answered:** option 3, successes only. **Pushed back on** losing the `NoSourcesError` rows, which are the ones that tell you which sources to add → reply pending.

### Round 10 — Q12: Config ceremony
Asked about the two config objects that currently encode no decision.
Lean was option 2 (delete `RetrievalSettings`, keep the LLM settings). **User answered:** option 3, keep both. **Pushed back on** invisible drift between the copy and the default → reply pending.

Verified for the next round: with the current policy the site filters run 170-198 characters and 17-19 words, while `_trim_query` caps the head at 140 characters and 20 words. Worst case is 339 of 400 characters and 39 of 50 words, so the domain-dropping loop in `build_batch_query` cannot execute.

### Round 11 — Q13: Dead defensive code in search.py
Asked whether the unreachable budget loop and the two-function extraction wrapper survive.
Lean was option 2 (delete the extraction pair, keep the loop). **User answered:** option 3, keep both. **Pushed back on** the extraction pair having no defence and the loop being untestable as written → reply pending.

Verified for the next round: `thread_id` appears only inside `graph.py`. No caller anywhere in `app/src` or `app/tests` ever passes one, so `build_runtime_config` always returns `{"configurable": {}}` and its validation branch is unreachable.

### Round 12 — Q14: The graph.py helper trio
Asked which of the three build helpers survive the move to construction-only.
Lean was option 1 (delete `build_runtime_config`). **User answered:** option 3, keep all three. **Pushed back on** the unreachable validation branch → reply pending.

### Round 13 — Q15: Execution and test strategy
Asked how the settled changes get made and what happens to the tests they invalidate.
Lean was option 2 (two branches). **User answered:** option 1. **Pushed back on** bisect-ability → reply pending.

### Round 14 — Q16: The two database.py leftovers
Asked the last two open details, both deferred from earlier rounds.
Lean was option 1 (leave the column, add the log line). **User answered:** option 4. **Pushed back on** silent failure making a dead database look like an empty one → held.
