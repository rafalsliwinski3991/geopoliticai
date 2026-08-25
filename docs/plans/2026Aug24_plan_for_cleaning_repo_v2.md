# Repo Cleanup Plan v2 — 2026-08-24

**Supersedes:** `docs/plans/2026Aug24_plan_for_cleaning_repo_v1.md`

**Verified against:** the current repository, `app/uv.lock` (`langgraph==1.0.1`, `langchain-core==0.3.83`, `langchain-openai==0.3.35`), and the official LangGraph documentation for retries and streaming.

## Summary

Keep the v1 scope: remove dead claim-extraction state, stop recompiling the graph per API request, make provider failures observable and recoverable, and stream the final synthesis to the browser. The v1 plan is directionally correct, but it needs four material corrections:

1. Removing `extract_claims` also requires deleting its API progress labels and updating both `AGENTS.md` and `CLAUDE.md`.
2. The graph does not need one cached instance per infosphere. Its structure is language-independent, so one compiled graph can serve English and Polish through `RunnableConfig`.
3. A node-level `try/except` prevents LangGraph's `RetryPolicy` from seeing the exception. The v1 proposal therefore would not retry `cross_check_facts` or `compose_final` before using their fallbacks. With the locked LangGraph 1.0.1, use call-level transient retries followed by explicit node fallbacks instead of relying on the newer LangGraph error-handler API.
4. Final-answer streaming needs a plain-text model call, explicit callback/config propagation, safe extraction of text chunks, frontend reset behavior, and tests that exclude tokens from other LLM nodes.

No checkpointing, HITL, model-tier changes, Polish loaded-language work, tracing, or repository-root deletion is included in this pass.

## Interface changes

- `PipelineState` gains `errors: Annotated[list[ErrorRecord], operator.add]`; this remains an internal graph-state field.
- The SSE endpoint adds an additive event: `{"type": "token", "content": "..."}`. Existing `progress`, `result`, and `error` events remain compatible.
- `graph.py` adds `invoke_pipeline(compiled_graph, ...)` and makes `build_graph()` independent of infosphere/report mode. The CLI-facing `run_pipeline(...)` signature remains compatible.
- Unexpected sync failures become an explicit sanitized HTTP 500 response. Streaming failures keep the existing SSE `error` shape but no longer expose raw exception text.
- No dependency or lockfile update is required.

## 1. Remove the dead `extract_claims` stage

The current node flattens lane claims into `state["extracted_claims"]`, but `cross_check_facts_agent` independently reads the four lane claim lists. No downstream node consumes the flattened output.

### Implementation

- Delete `app/src/nodes/extract_claims.py` and remove its import/export from `nodes/__init__.py`.
- Remove `extracted_claims` from `PipelineState` and `build_initial_pipeline_state`; also remove the now-unused `Any` import from `models.py` if no other reference remains.
- Remove the node and its incoming/outgoing edges from `graph.py`; route referee `continue` directly to `cross_check_facts`.
- Remove `extract_claims` from both Polish and English progress-label mappings in `api.py`.
- Update the pipeline topology and operating notes in both `AGENTS.md` and `CLAUDE.md`.

### Tests and acceptance

- Extend the graph topology test to assert that `extract_claims` is absent and `cross_check_facts` is present.
- Add direct tests for `_route_after_referee`: `blocked=False` returns `continue`, `blocked=True` returns `blocked`, and a missing/invalid report returns `blocked`.
- Confirm `rg "extract_claims|extracted_claims" app/src app/tests AGENTS.md CLAUDE.md` returns no matches.

## 2. Compile one reusable graph

`build_graph(infosphere=..., report_mode=...)` currently validates those arguments but does not bind them into any node. Language, source pools, and report mode are already resolved per invocation from `RunnableConfig`; compiled graph structure is identical for every request.

### Implementation

- Change `build_graph` to accept only the structural option `checkpointer`. Keep `graph = build_graph()` as the single module-level compiled graph used by LangGraph Studio and normal uncheckpointed execution.
- Add `invoke_pipeline(compiled_graph, query, infosphere, report_mode, thread_id=None)`. It must normalize the report mode, build a fresh initial state, build per-request runtime config, call the supplied graph, and return `final_output`.
- Keep `run_pipeline(...)` as the CLI-compatible convenience function. When `checkpointer is None`, invoke the module-level graph; when a caller supplies a checkpointer, compile a dedicated graph with that checkpointer and invoke it.
- In `api.py`, import the module-level graph as `pipeline_graph`. Use it in both endpoints; do not create `_graphs` keyed by language and do not compile graphs in FastAPI lifespan.
- Run the synchronous `invoke_pipeline` call through `starlette.concurrency.run_in_threadpool` so the async FastAPI endpoint does not block the event loop while synchronous search/model calls run.
- Remove the unused `BackgroundTasks` parameter from the streaming endpoint. Keep it on the sync endpoint for deferred output logging.

### Tests and acceptance

- Replace API tests that patch `api.build_graph`/`api.run_pipeline` with patches of `api.pipeline_graph` or `api.invoke_pipeline`, as appropriate.
- Add an `invoke_pipeline` unit test using a fake compiled graph; assert English and Polish calls receive distinct language/source runtime config and independent initial state.
- Add an API test proving the sync endpoint awaits the threadpool invocation and returns its result.
- Add a regression test or spy showing repeated API requests do not call `build_graph`.
- Preserve `app/langgraph.json` compatibility with the module-level `graph` export.

## 3. Make retries, degradation, and errors consistent

Use retries at the provider-call boundary, where an exhausted retry can still be converted into a deterministic node result. Do not combine a broad node `try/except` with `RetryPolicy` and claim that LangGraph will retry it: once the exception is caught, the policy never sees it.

### 3.1 Typed error state

- Add `ErrorRecord` in `models.py` with `node`, `error_type`, and `message` fields.
- Add `errors: Annotated[list[ErrorRecord], operator.add]` to `PipelineState` and initialize it to `[]`.
- Add a small helper for constructing error records so nodes use one stable shape. Keep raw messages in state/logging only; render only a localized count to users.

### 3.2 Provider-call retries

- In `llm.py`, wrap structured LLM invocations in at most **2 total attempts** for transient failures only: connection/timeouts, rate limits, and provider 5xx responses. Back off once for 1 second. Do not retry authentication, permission, bad-request, schema-validation, or other deterministic failures.
- Preserve the existing output-token-limit escalation. A transient retry restarts the whole structured call; token-limit escalation remains responsible only for truncated structured JSON.
- Introduce `LLMInvocationError` and wrap final model/parsing failures with the original exception as the cause. Nodes catch this explicit boundary exception rather than swallowing arbitrary programming errors.
- In `search.py`, retry each Brave request up to **3 total attempts** for timeouts/transport errors, HTTP 429, and HTTP 5xx, using 0.5-second exponential backoff. Do not retry other 4xx responses.
- Introduce `SearchExhaustedError`. `web_searcher` should continue trying its configured domains as today, but raise this error when every attempted request failed. A successful response with zero in-scope results remains a valid empty search, and partial domain failures remain logged rather than surfaced as a degraded run.
- Do not add a new dependency; use the existing OpenAI/httpx exception types and a small internal retry helper. Tests must replace sleeping with a no-op.

### 3.3 Deterministic node fallbacks

- Search-pool nodes catch `SearchExhaustedError`, return an empty lane source update, and append one error record for that lane.
- `generic_analyst_agent` catches `LLMInvocationError`, skips further model repair prompts, builds claims from source notes (then its existing minimal fallback if necessary), and appends one lane-specific error record.
- `cross_check_facts_agent` treats fact-search exhaustion separately: record the search error and continue with already-collected lane sources. If its LLM call fails, return one deterministic `MISLEADING` `FactCheckResult` per input claim using `_fallback_result_for_claim`, rather than returning an empty fact-check list, and append an error record.
- `compose_final_agent` keeps its deterministic TRUE-claim fallback and appends an error record when the model call fails.
- Configuration errors such as a missing API key are not retryable. FastAPI already validates required environment variables during startup; CLI startup behavior remains unchanged.

### 3.4 User-visible and API behavior

- In `supervisor.py`, insert a localized degraded-run note immediately after the direct answer when `errors` is non-empty. Show only the number of affected pipeline stages, in both compact and full reports; never include raw exception messages.
- In the sync endpoint, keep `ValueError` as a sanitized 400 for invalid runtime arguments and convert any unexpected exception into a logged, generic HTTP 500 response.
- In the streaming endpoint, log unexpected exceptions but emit a localized generic message. Do not interpolate `str(exc)` into the SSE payload.

### Tests and acceptance

- Test transient classifiers: retry timeout/rate-limit/5xx, do not retry 4xx/auth/schema failures, and stop at the documented attempt count.
- Test all-search-failed versus successful-empty and partial-success Brave outcomes.
- Test analyst LLM failure returns fallback claims plus an error record.
- Test fact-search failure still permits fact-checking from lane sources.
- Test fact-check LLM failure returns one `MISLEADING` result per claim plus an error record.
- Extend compose-final fallback tests to assert the error record.
- Test supervisor degraded notes in English and Polish, compact and full modes, and assert raw exception text is absent.
- Test sync and streaming unexpected failures return sanitized client messages while preserving server-side exception logging.

## 4. Stream the final synthesis safely

`SynthesisOutput` contains only one string field. Replace this structured-output call with a plain-text call so LangChain can auto-stream chat-model chunks through the graph event stream. Keep structured outputs for every node that genuinely returns structured data.

### Backend implementation

- Add `TextOutputChain`/`invoke_text_chain` in `llm.py` using the same model, timeout, temperature, and output-token configuration as structured calls.
- Accept an optional `RunnableConfig` and pass it to the composed prompt/model runnable's `.invoke(...)`; `compose_final_agent` must pass its node config. This preserves callback/event propagation explicitly.
- Require the returned model content to be a string. Raise `LLMInvocationError` for empty/non-text output and let `compose_final_agent` use its deterministic fallback.
- Do not transiently retry the streaming text call in this pass: a failed retry after partial token emission would duplicate the draft. A partial draft is harmless because the terminal `result` or `error` event replaces/clears it.
- Switch `compose_final_agent` to plain text, remove `SynthesisOutput`, its coercion validator, and the JSON-only prompt instruction. Preserve `_ensure_short_answer_prefix` and the TRUE-claims-only prompt constraints.
- In the SSE loop, forward only `on_chat_model_stream` events whose `metadata.langgraph_node == "compose_final"`.
- Normalize chunk content through a helper that accepts string content and text content blocks; ignore tool-call/reasoning/non-text blocks. Emit non-empty text as `{"type":"token","content":...}`.
- Keep the final `result` event unchanged; token events are only a live synthesis preview, while `result` remains the complete supervisor-rendered report and the value persisted to the database.

### Frontend implementation

- Add `streamingDraft` to Alpine state and reset it at request start, `result`, SSE `error`, fetch/parse failure, and timeout.
- Append `token.content` without Markdown interpretation and render it in a safe `x-text` live-response bubble adjacent to the progress block.
- On `result`, clear the draft before adding the final bot message so users never see duplicate draft/final answers.
- Keep unknown-event behavior unchanged so older/newer clients remain tolerant of additive SSE events.

### Tests and acceptance

- Update compose-final tests to mock `invoke_text_chain` returning a string and verify only TRUE claims reach the prompt.
- Add API stream tests that forward compose-final text chunks, ignore analyst chunks, preserve progress events, and still finish with one complete `result` event.
- Cover string chunks, text-block chunks, empty chunks, and non-text chunks.
- Manually verify in both infospheres that the draft grows before completion, disappears when the final report arrives, and is cleared on failure.

## Landing order and completion gate

1. Remove `extract_claims` and update topology/docs.
2. Introduce the single compiled graph and `invoke_pipeline`.
3. Add provider retries, error state, deterministic fallbacks, and sanitized API errors.
4. Convert final composition to plain text and add token SSE/frontend handling.

Before merging:

- Run `make test` and `make integration_tests` from `app/`.
- Run `make lint` from `app/` and resolve strict mypy/ruff failures without weakening checks.
- Run the focused API, graph-routing, retry, search, fact-check, compose-final, and supervisor tests independently.
- Start the development stack and manually exercise English and Polish streaming plus a forced provider failure.
- Re-run repository searches for removed symbols and stale claims that graphs are rebuilt per request.
- Ensure `AGENTS.md` and `CLAUDE.md` describe the final topology, shared compiled graph, `errors` state, and token-capable SSE behavior.

## Verification note

The repository inspection found no existing v2 file and no implementation of these changes. The host environment did not have `uv`, and the existing `geo_venv` did not contain LangGraph, so the baseline Python tests could not be executed during plan verification. Running the current suite is therefore the first implementation gate, not evidence to defer until the end.
