# Repo Cleanup Plan v3 — 2026-08-24

**Supersedes:** `docs/plans/2026Aug24_plan_for_cleaning_repo_v2.md`

**Derived from:** the v2 plan, re-verified against the working tree, plus the design decisions
recorded in `brainstorming/2026Aug24_brainstorm_v1.md` (16 rounds).

**Verified against:** the current repository; `app/uv.lock` (`langgraph==1.0.1`,
`langchain-core==0.3.83`, `langchain-openai==0.3.35`); and the LangGraph documentation for
`recursion_limit` placement.

---

## Summary

v2's four areas survive: remove dead claim-extraction state, stop recompiling the graph per API
request, make provider failures observable and recoverable, and stream the final synthesis to the
browser. v3 changes *how* three of them are done and adds a fifth area.

Material differences from v2:

1. **No hand-rolled LLM retry.** `ChatOpenAI` already retries transient failures (the SDK default
   is `max_retries=2`). v2's wrapper would have multiplied attempts. v3 sets `max_retries`
   explicitly instead, and keeps only the genuinely-missing half of v2 §3.2: the
   `LLMInvocationError` / `SearchExhaustedError` boundaries and the node fallbacks.
2. **The output-token escalation loop is deleted, not preserved.** v2 said "preserve the existing
   output-token-limit escalation." Its trigger is substring-matching on exception prose, which fails
   silently on a library bump. v3 removes it and sets a single ceiling at the value the loop already
   reached.
3. **No degraded-run note in the report.** v2 §3.4 would print a count of affected pipeline stages.
   That number is an error-record count rather than a stage count, uses implementation vocabulary,
   fires on routine partial-search failures, and is blind to lanes that return zero results without
   raising. v3 states lane coverage in the fact-check summary line that already exists instead. All
   of v2 §3.3's error plumbing is retained — it is for operators and logs, not for the report body.
4. **No 400 branch on the sync endpoint.** Every `ValueError` that can reach that handler today is a
   server-side fault; Pydantic already returns 422 for the only client-supplied fields.
5. **`checkpointer` is removed, not preserved.** No caller passes one, and one branch of v2's
   `run_pipeline` conditional could never execute.
6. **New: area 5, documentation correctness.** `CLAUDE.md` asserts three things about the code that
   are false independent of this pass, and both context files document `recursion_limit` with an API
   that does not exist.

Explicitly **not** in this pass: checkpointing, HITL, model-tier changes, tracing, repository-root
deletion, the Polish loaded-language gate, the TRUE-only synthesis gate, and `recursion_limit`
itself. Reasons for the last three are recorded in "Declined, with reasoning" below.

---

## Interface changes

- `PipelineState` gains `errors: Annotated[list[ErrorRecord], operator.add]` and loses
  `extracted_claims`. Both are internal graph-state fields.
- The SSE endpoint adds an additive event: `{"type": "token", "content": "..."}`. Existing
  `progress`, `result`, and `error` events remain compatible.
- `graph.py` adds `invoke_pipeline(compiled_graph, ...)`; `build_graph()` becomes parameterless.
  `run_pipeline(query, infosphere, report_mode, thread_id=None)` stays CLI-compatible minus its
  unused `checkpointer` argument.
- `models.py` gains `normalize_report_mode`, replacing two duplicate private implementations.
- Unexpected sync failures become a sanitized HTTP 500. Streaming failures keep the existing SSE
  `error` shape but no longer expose raw exception text.
- `DEFAULT_OPENAI_MAX_OUTPUT_TOKENS` changes from `4096` to `16_384`.
- No dependency or lockfile update is required.

---

## 1. Remove the dead `extract_claims` stage

`extract_claims_for_verification` flattens lane claims into `state["extracted_claims"]`, but
`cross_check_facts_agent` independently reads the four lane claim lists (`cross_check_facts.py:117-122`).
No node reads the flattened output.

### 1.1 Delete the node

Delete `app/src/nodes/extract_claims.py`.

`app/src/nodes/__init__.py` — remove both the import and the `__all__` entry:

```diff
 from nodes.cross_check_facts import cross_check_facts_agent
-from nodes.extract_claims import extract_claims_for_verification
 from nodes.ingest_request import ingest_request
```

```diff
     "cross_check_facts_agent",
-    "extract_claims_for_verification",
     "ingest_request",
```

### 1.2 Remove the state field

`app/src/models.py` — drop the field from `PipelineState` and from
`build_initial_pipeline_state`:

```diff
     research_plan: ResearchPlan
     referee_report: RefereeReport
-    extracted_claims: Annotated[list[dict[str, Any]], operator.add]
```

```diff
         "research_plan": ResearchPlan(),
         "referee_report": RefereeReport(),
-        "extracted_claims": [],
     }
```

`extracted_claims` is the only *code* use of `Any` in `models.py` (the remaining occurrences at
lines 128-129 are docstring prose), so the import narrows:

```diff
-from typing import Annotated, Any, Literal, TypedDict
+from typing import Annotated, Literal, TypedDict
```

### 1.3 Rewire the graph

`app/src/graph.py` — remove the node registration, the two edges, and redirect the referee's
`continue` branch:

```diff
     graph.add_node("referee_blocked_summary", summarize_referee_block)
-    graph.add_node("extract_claims", extract_claims_for_verification)
     graph.add_node("cross_check_facts", cross_check_facts_agent)
```

```diff
     graph.add_conditional_edges(
         "referee",
         _route_after_referee,
         {
-            "continue": "extract_claims",
+            "continue": "cross_check_facts",
             "blocked": "referee_blocked_summary",
         },
     )
     graph.add_edge("referee_blocked_summary", "supervisor")
-    graph.add_edge("extract_claims", "cross_check_facts")
     graph.add_edge("cross_check_facts", "compose_final")
```

…and drop `extract_claims_for_verification` from the `from nodes import (...)` block.

### 1.4 Remove the progress labels

`app/src/api.py` — delete one entry from each mapping:

```diff
     "referee_blocked_summary": "Podsumowuję blokadę...",
-    "extract_claims": "Wyodrębniam twierdzenia...",
     "cross_check_facts": "Sprawdzam fakty krzyżowo...",
```

```diff
     "referee_blocked_summary": "Summarizing block...",
-    "extract_claims": "Extracting claims...",
     "cross_check_facts": "Cross-checking facts...",
```

### Tests and acceptance

- Extend the graph topology test to assert `extract_claims` is absent and `cross_check_facts` is
  present.
- Add direct tests for `_route_after_referee`: `blocked=False` returns `continue`, `blocked=True`
  returns `blocked`, and a missing or non-`RefereeReport` value returns `blocked`.
- `rg "extract_claims|extracted_claims" app/src app/tests AGENTS.md CLAUDE.md` returns no matches.

---

## 2. Compile one reusable graph

`build_graph(infosphere=..., report_mode=...)` validates both arguments and binds neither. Language,
source pools, and report mode are already resolved per invocation from `RunnableConfig` via
`nodes/runtime_config.py`. The compiled structure is identical for every request, and a module-level
`graph = build_graph()` already exists at `graph.py:165`.

### 2.1 `build_graph` becomes parameterless

```diff
-def build_graph(
-    infosphere: str = DEFAULT_INFOSPHERE,
-    report_mode: str = DEFAULT_REPORT_MODE,
-    *,
-    checkpointer: Any | None = None,
-) -> Any:
+def build_graph() -> Any:
     """Construct and compile the LangGraph pipeline."""
-    _normalize_report_mode(report_mode)
-    get_infosphere_sources(normalize_language(infosphere))
     graph = StateGraph(PipelineState)
```

and at the end:

```diff
-    if checkpointer is None:
-        return graph.compile(name="GeopoliticAI")
-    return graph.compile(checkpointer=checkpointer, name="GeopoliticAI")
+    return graph.compile(name="GeopoliticAI")
```

`checkpointer` is dropped rather than kept (see "Declined, with reasoning"). `graph = build_graph()`
at module scope is unchanged, preserving `app/langgraph.json`'s `src/graph.py:graph` export.

### 2.2 Add `invoke_pipeline`

New function in `graph.py`. The graph is a parameter so tests can inject a fake:

```python
def invoke_pipeline(
    compiled_graph: Any,
    query: str,
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    thread_id: str | None = None,
) -> str:
    """Run one request against an already-compiled graph and return the rendered report."""
    normalized_report_mode = normalize_report_mode(report_mode)
    language = normalize_language(infosphere)
    initial_state = build_initial_pipeline_state(query, language=language)
    config = build_runtime_config(
        infosphere=infosphere,
        report_mode=normalized_report_mode,
        thread_id=thread_id,
    )
    result = compiled_graph.invoke(initial_state, config=config)
    return str(result["final_output"])
```

`run_pipeline` becomes a thin CLI-facing wrapper over the module-level graph:

```python
def run_pipeline(
    query: str,
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    thread_id: str | None = None,
) -> str:
    """Execute the pipeline and return the final rendered report."""
    return invoke_pipeline(
        graph, query, infosphere, report_mode, thread_id=thread_id
    )
```

Note `graph` is defined *below* these functions today; keep the module-level
`graph = build_graph()` where it is and let `run_pipeline` resolve it at call time.

### 2.3 Rewire the API

`app/src/api.py`:

```diff
-from graph import build_graph, build_runtime_config, run_pipeline
-from models import build_initial_pipeline_state, normalize_language
+from graph import graph as pipeline_graph
+from graph import invoke_pipeline
```

`build_runtime_config`, `build_initial_pipeline_state`, and `normalize_language` are no longer
needed in `api.py` — `invoke_pipeline` owns all three for the sync path. The streaming path still
needs `build_runtime_config`, `build_initial_pipeline_state`, and `normalize_language`, so keep
those three imports and drop only `build_graph` / `run_pipeline`.

Streaming endpoint — use the shared graph and drop the unused `BackgroundTasks`:

```diff
 async def run_pipeline_stream_endpoint(
     payload: RunPipelineRequest,
     request: Request,
-    background_tasks: BackgroundTasks,
 ) -> StreamingResponse:
```

```diff
     async def _generate() -> AsyncGenerator[str, None]:
         try:
-            graph = build_graph(infosphere=payload.infosphere)
             initial_state = build_initial_pipeline_state(
                 payload.query,
                 language=normalize_language(payload.infosphere),
             )
             config = build_runtime_config(infosphere=payload.infosphere)
```

```diff
-            async for event in graph.astream_events(
+            async for event in pipeline_graph.astream_events(
                 initial_state, config=config, version="v2"
             ):
```

Sync endpoint — run the synchronous invocation off the event loop. It is currently `async def`
calling a fully synchronous `run_pipeline`, which blocks every other request for the duration of a
multi-minute pipeline run:

```diff
+from starlette.concurrency import run_in_threadpool
```

```diff
-    try:
-        output = run_pipeline(payload.query, infosphere=payload.infosphere)
-    except ValueError as exc:
-        raise HTTPException(status_code=400, detail=str(exc)) from exc
+    output = await run_in_threadpool(
+        invoke_pipeline, pipeline_graph, payload.query, payload.infosphere
+    )
```

Error handling for this endpoint is specified in §3.4. `BackgroundTasks` stays on the sync endpoint
— it is genuinely used for deferred output logging.

### Tests and acceptance

- Replace API tests patching `api.build_graph` / `api.run_pipeline` with patches of
  `api.pipeline_graph` or `api.invoke_pipeline`.
- Add an `invoke_pipeline` unit test with a fake compiled graph; assert English and Polish calls
  receive distinct `language` / `infosphere_sources` runtime config and independent initial state.
- Add an API test proving the sync endpoint awaits the threadpool invocation and returns its result.
- Add a spy test showing repeated API requests never call `build_graph`.
- `app/langgraph.json` still resolves `src/graph.py:graph`.

---

## 3. Boundary exceptions, deterministic fallbacks, typed errors

Retries belong where the SDK already provides them. Do not wrap a node in `try/except` and claim
LangGraph's `RetryPolicy` will retry it — once the exception is caught, the policy never sees it.

### 3.1 Typed error state

`app/src/models.py`:

```python
class ErrorRecord(TypedDict):
    """One recoverable failure, recorded for operators rather than readers."""

    node: str
    error_type: str
    message: str


def build_error_record(node: str, exc: Exception) -> ErrorRecord:
    """Construct one error record so every node emits the same shape."""
    return {"node": node, "error_type": type(exc).__name__, "message": str(exc)}
```

```diff
     referee_report: RefereeReport
+    errors: Annotated[list[ErrorRecord], operator.add]
```

```diff
         "referee_report": RefereeReport(),
+        "errors": [],
     }
```

Raw messages stay in state and logs only. Nothing in `errors` is rendered into the report — see
§3.4 and §5.

### 3.2 Boundary exceptions and explicit retry configuration

**`app/src/llm.py` — make `max_retries` visible, delete the escalation loop.**

`ChatOpenAI` is constructed today with no `max_retries`, so the SDK default of `2` is already
active and already retries connection errors, timeouts, 429s, and provider 5xx. v2's proposed
wrapper would have compounded to six requests per structured call. Set the value explicitly instead
and leave the behavior unchanged.

Delete outright: `MAX_STRUCTURED_OUTPUT_RETRY_TOKENS`, `LENGTH_LIMIT_ERROR_MARKERS`,
`_is_length_limit_error`, `_structured_output_token_limits`, and the whole `for token_limit in
token_limits:` loop including its unreachable `else:` branch (`llm.py:97-100` — every iteration
breaks, raises, or continues, so the loop can never complete without breaking).

`StructuredOutputChain.invoke` becomes:

```python
DEFAULT_MAX_RETRIES = 2
"""Matches the langchain-openai default. Kept explicit so the retry budget is visible.

Worst case: 4 sequential LLM calls x (1 + DEFAULT_MAX_RETRIES) attempts x
OPENAI_TIMEOUT_SECONDS. At the 60s default that is ~12 minutes, which exceeds the
frontend's 10-minute abort (frontend/index.html:473). See "Known tightness" below.
"""


class LLMInvocationError(RuntimeError):
    """Raised when a model call or its structured parsing fails unrecoverably."""


@dataclass
class StructuredOutputChain:
    schema: Type[BaseModel]
    system_prompt: str
    human_prompt: str
    temperature: float = 0.0
    model: str | None = None

    def invoke(self, variables: dict[str, Any]) -> BaseModel:
        model = self.model or get_model()
        prompt = ChatPromptTemplate.from_messages(
            [("system", self.system_prompt), ("human", self.human_prompt)]
        )
        llm = ChatOpenAI(
            model=model,
            temperature=self.temperature,
            max_completion_tokens=get_openai_max_output_tokens(),
            timeout=get_openai_timeout_seconds(),
            max_retries=DEFAULT_MAX_RETRIES,
        )
        try:
            result = (prompt | llm.with_structured_output(self.schema)).invoke(variables)
        except Exception as exc:
            raise LLMInvocationError(
                f"Structured call failed for schema={self.schema.__name__}"
            ) from exc
        if isinstance(result, self.schema):
            return result
        return self.schema.model_validate(cast(Any, result))
```

**`app/src/config.py` — one ceiling instead of three tiers.**

```diff
-DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 4096
+# gpt-4o-mini's maximum output. This is the value the removed escalation loop
+# already climbed to, so a single ceiling here is behavior-preserving.
+# Re-check this if OPENAI_MODEL / AGENT_MODEL_NAMES ever names a model with a
+# smaller output cap — an over-large request is a hard provider 400, not a
+# degradation.
+DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 16_384
```

**`app/src/search.py` — `SearchExhaustedError`, retry only the combined-query fallback.**

`web_searcher` already issues one Brave request per allowed domain (~3 per lane) and falls back to
a combined `site: OR site:` query when none produce results. Per-domain failures already
`continue` past (`search.py:159`). That loop *is* the redundancy; retrying inside it would push a
5-lane run toward 60 Brave requests against a 1 req/s free tier.

```python
class SearchExhaustedError(RuntimeError):
    """Raised when every Brave request attempted for a lane failed."""
```

- Add a small internal retry helper: up to **3 total attempts** with 0.5s exponential backoff, for
  `httpx.TimeoutException`, `httpx.TransportError`, HTTP 429, and HTTP 5xx only. Do not retry other
  4xx.
- Apply it to the **combined-query call only** (`search.py:203-212`). Leave the per-domain loop
  as-is.
- Track whether any per-domain request succeeded. Raise `SearchExhaustedError` only when every
  per-domain request failed **and** the combined query also failed after its retries. A successful
  response with zero in-scope results is a valid empty search. Partial domain failure stays logged,
  not surfaced.
- Tests must patch the sleep to a no-op.

### 3.3 Deterministic node fallbacks

Each node catches the explicit boundary exception — never bare `Exception`, which today swallows
genuine programming errors at `compose_final.py:180`.

- **Search-pool nodes** (`nodes/search_pools.py`) catch `SearchExhaustedError`, return an empty lane
  source list, and append one error record for that lane.
- **`generic_analyst_agent`** catches `LLMInvocationError`, skips the zero-claim repair prompt,
  builds claims from source notes via `_fallback_claims_from_sources` (then its existing minimal
  fallback if needed), and appends one lane-specific error record.
- **`cross_check_facts_agent`** treats the two failures separately. Fact-search exhaustion: record
  the error, continue with already-collected lane sources. LLM failure: return one deterministic
  `MISLEADING` `FactCheckResult` per input claim via `_fallback_result_for_claim` — not an empty
  list — and append an error record.
- **`compose_final_agent`** keeps its deterministic TRUE-claim fallback and appends an error record.
  Its bare `except Exception` narrows to `except LLMInvocationError`.
- Configuration errors (missing API key) are not retryable and get no fallback.

### 3.4 API error handling

**Sync endpoint.** Delete the `except ValueError` → 400 branch entirely. Every `ValueError` able to
reach that handler today is a server-side fault: `search.py:124` (missing `BRAVE_SEARCH_KEY`),
`config.py:116` (`require_env`), `config.py:217` (unsupported infosphere), and `llm.py`'s internal
guard. The client-argument raise sites — `graph.py:42` / `supervisor.py:192` (`report_mode`) and
`graph.py:69` (`thread_id`) — are unreachable from HTTP, because neither endpoint passes either
parameter. Empty queries are rejected by Pydantic at 422 before the handler runs.

```python
    try:
        output = await run_in_threadpool(
            invoke_pipeline, pipeline_graph, payload.query, payload.infosphere
        )
    except Exception:
        logger.exception("Pipeline failed unexpectedly.")
        raise HTTPException(status_code=500, detail="Internal server error.") from None
```

If `report_mode` is ever exposed to callers, its validation and a 400 path get added then, alongside
the parameter.

**Streaming endpoint.** Collapse the two handlers into one. Log the exception server-side; emit a
localized generic message. Never interpolate `str(exc)` into the SSE payload:

```diff
-        except ValueError as exc:
-            logger.warning("Streaming pipeline rejected request: %s", exc)
-            data = json.dumps({"type": "error", "message": str(exc)})
-            yield f"data: {data}\n\n"
-        except Exception as exc:
+        except Exception:
             logger.exception("Streaming pipeline failed unexpectedly.")
-            msg = unexpected_msg.format(exc)
-            data = json.dumps({"type": "error", "message": msg})
+            data = json.dumps({"type": "error", "message": unexpected_msg})
             yield f"data: {data}\n\n"
```

`unexpected_msg` becomes a plain localized string rather than a format template:

```diff
     unexpected_msg = (
-        "Nieoczekiwany błąd: {}"
+        "Wystąpił nieoczekiwany błąd. Spróbuj ponownie."
         if payload.infosphere == "polish"
-        else "Unexpected error: {}"
+        else "An unexpected error occurred. Please try again."
     )
```

**No degraded-run note is added to the report.** See §5 for what the reader is told instead.

### Tests and acceptance

- Test the search transient classifier: retries timeout / 429 / 5xx, does not retry other 4xx, stops
  at 3 attempts.
- Test all-domains-failed-and-combined-failed raises `SearchExhaustedError`; test successful-empty
  and partial-success do not.
- Test analyst `LLMInvocationError` yields fallback claims plus one error record.
- Test fact-search exhaustion still permits fact-checking from lane sources.
- Test fact-check LLM failure returns one `MISLEADING` result per claim plus an error record.
- Extend compose-final fallback tests to assert the error record and that the narrowed
  `except LLMInvocationError` lets an unrelated `TypeError` propagate.
- Test sync and streaming unexpected failures return sanitized messages while the server-side
  `logger.exception` still fires.
- Assert `str(exc)` text appears in no client-visible payload.

---

## 4. Stream the final synthesis

`SynthesisOutput` holds one string field. Replacing that structured call with a plain-text call lets
LangChain auto-stream chat-model chunks through the graph event stream. Every other node keeps
structured output.

### 4.1 Backend

**`llm.py`** — add `TextOutputChain` / `invoke_text_chain` alongside the structured pair, using the
same model, timeout, temperature, and token configuration. It accepts an optional `RunnableConfig`
and passes it to `.invoke(...)` so callback and event propagation is explicit rather than implicit.
Require string content; raise `LLMInvocationError` on empty or non-text output.

**`compose_final.py`** — delete `SynthesisOutput`, its `_coerce_synthesis_to_text` validator, and
the trailing `"Return JSON with exactly one key: synthesis (string)."` prompt line. Preserve
`_ensure_short_answer_prefix` and the TRUE-claims-only constraints. Pass the node's `config`
through. Narrow the exception:

```diff
-    except Exception as exc:
+    except LLMInvocationError as exc:
         logger.warning("Compose final: LLM synthesis failed, using fallback: %s", exc)
-        return {"synthesis": _fallback_from_true_claims(true_claims, language)}
+        return {
+            "synthesis": _fallback_from_true_claims(true_claims, language),
+            "errors": [build_error_record("compose_final", exc)],
+        }
```

Do **not** transiently retry the streaming text call: a retry after partial token emission would
duplicate the draft. A partial draft is harmless because the terminal `result` or `error` event
clears it.

**`api.py` SSE loop** — forward only `on_chat_model_stream` events from this one node:

```python
                if (
                    etype == "on_chat_model_stream"
                    and event.get("metadata", {}).get("langgraph_node") == "compose_final"
                ):
                    text = _chunk_text(event.get("data", {}).get("chunk"))
                    if text:
                        data = json.dumps({"type": "token", "content": text})
                        yield f"data: {data}\n\n"
```

`_chunk_text` normalizes `chunk.content`: a plain string passes through; a list of content blocks
contributes only `type == "text"` entries; tool-call, reasoning, and other non-text blocks are
ignored. The final `result` event is unchanged — token events are a live preview, while `result`
remains the complete supervisor-rendered report and the value persisted to the database.

### 4.2 Frontend

The streamed text is **not** the final report. `compose_final` emits `state["synthesis"]`;
`supervisor_step` then splits it at `supervisor.py:247` via `_split_direct_answer_and_details`,
strips the `"Short answer:"` prefix, and redistributes the halves into `Answer:` and `Rationale:`
inside a scaffold that also carries `Question:`, four claim lanes, and a fact-check tally. In
`compact` mode `_extract_reason_bullets` keeps at most three bullets truncated to 220 characters and
drops the claims section entirely.

So the draft is genuinely provisional, and the UI must say so — otherwise the swap reads as the app
retracting its own answer.

- Add `streamingDraft: ""` to the Alpine `chat` component state.
- Reset it at request start, on `result`, on SSE `error`, on fetch/parse failure, and on the
  10-minute `AbortController` timeout (`frontend/index.html:473`).
- Append `token.content` and render via `x-text` (never `x-html`, never through `marked`) in a
  bubble adjacent to the progress block.
- Style it as explicitly provisional: dimmed, italic, without the standard `.message` bubble chrome.
- Add one caption string to **both** branches of the existing `I18N` table
  (`frontend/index.html:405-437`), rendered through the existing `t()` helper:
  `drafting: "Szkic odpowiedzi…"` / `drafting: "Drafting answer…"`.
- On `result`, clear the draft **before** pushing the final bot message.
- Keep unknown-event handling unchanged so older and newer clients tolerate additive SSE events.

This also improves the failure path: because the text call is deliberately not retried, a failed
`compose_final` leaves the draft frozen mid-sentence. A region captioned "Drafting answer…" reads
far better in that state than a bubble styled as a finished answer.

### Tests and acceptance

- Update compose-final tests to mock `invoke_text_chain` returning a string; verify only TRUE claims
  reach the prompt.
- Add API stream tests: compose-final chunks are forwarded; analyst chunks are ignored; progress
  events are preserved; exactly one complete `result` event still terminates the stream.
- Cover string chunks, text-block chunks, empty chunks, and non-text blocks in `_chunk_text`.
- Manually verify in both infospheres that the draft grows, is captioned, disappears when the final
  report arrives, and is cleared on failure.

---

## 5. Report coverage, shared validation, and documentation correctness

### 5.1 State lane coverage in the report

Instead of a degraded-run note, extend the fact-check summary line that already terminates both
render modes, using data already in state:

```python
def _lane_coverage(state: PipelineState) -> tuple[int, int]:
    """Return (lanes with at least one source, total lanes)."""
    lanes = (
        state["left_sources"],
        state["centrist_sources"],
        state["right_sources"],
        state["people_sources"],
    )
    return sum(1 for lane in lanes if lane), len(lanes)
```

Full mode:

```diff
-            lines.append(
-                f"{facts_label} {len(state['fact_checks'])} verdicts from "
-                f"{len(state['fact_sources'])} sources."
-            )
+            available, total = _lane_coverage(state)
+            lines.append(
+                f"{facts_label} {len(state['fact_checks'])} verdicts from "
+                f"{len(state['fact_sources'])} sources "
+                f"({coverage_label(available, total)})."
+            )
```

Compact mode gets the same suffix appended to its existing summary line. `coverage_label` is
localized: `"{a} z {b} perspektyw dostępnych"` / `"{a} of {b} perspectives available"`.

This measures the outcome rather than the failures, so it also catches the case `errors` cannot: a
lane whose Brave requests all succeed but return zero in-scope results raises nothing, appends no
error record, and is invisible to any error-count approach. It is self-denominating, and for a tool
whose premise is multi-perspective balance, which perspectives were actually available is the most
load-bearing caveat available.

**No test currently asserts on any `supervisor.py` output** — `rg` across `app/tests/` finds zero.
Nothing breaks, but these will be the first tests for that layer. Cover: all four lanes populated,
two populated, zero populated, in both languages and both render modes.

### 5.2 One `report_mode` validator

`_normalize_report_mode` is implemented twice with identical checks and identical error messages:
`graph.py:38-42` and inline at `supervisor.py:190-192`.

**It cannot live in `graph.py`.** `graph.py` does `from nodes import (...)`, so
`nodes/supervisor.py` importing from `graph.py` would be circular. Put it in `models.py`, which both
modules already import from and which already owns `normalize_language`:

```python
def normalize_report_mode(value: str) -> str:
    """Normalize and validate the report rendering mode."""
    normalized = str(value).strip().lower()
    if normalized not in {"compact", "full"}:
        raise ValueError("report_mode must be one of: compact, full.")
    return normalized
```

`graph.py` and `nodes/supervisor.py` both import and call it; both private copies are deleted.
`nodes/runtime_config.py`'s `runtime_report_mode` keeps its lenient lowercase-and-return behavior —
it reads an already-validated value out of config and should not raise mid-run.

`report_mode` stays CLI-only. `cli.py:29-34` exposes `--report {compact,full}` defaulting to
`compact`; neither HTTP endpoint passes it, so API requests always render `full`. That split is
deliberate and should be stated in the docs, not silently reconciled.

### 5.3 Documentation correctness

Three claims in `CLAUDE.md` are false independent of this pass, all inside sections this pass
rewrites anyway. `AGENTS.md` already carries correct wording for two of them — it was updated during
the refactor that created `nodes/` and `runtime_config.py`; `CLAUDE.md` was not.

| Location | Current text | Correction |
|---|---|---|
| `CLAUDE.md:11` | "Modules use bare `from agents import ...`" | No `agents` package exists — it was merged into `nodes/`. Copy `AGENTS.md:12`, which says `from nodes import ...` and also documents the `app/src/nodes/` package that `CLAUDE.md` never mentions. |
| `CLAUDE.md:36` | `llm.py` "wraps both the Responses API and Chat Completions with JSON-mode output and graceful retries for `max_completion_tokens`/`temperature` compatibility issues across model variants" | None of this exists. `llm.py` builds a `ChatOpenAI` and calls `.with_structured_output()`. Rewrite to describe the post-§3.2 module: one structured chain, one text chain, explicit `max_retries`, `LLMInvocationError` boundary, single output-token ceiling. |
| `CLAUDE.md:548` | infosphere is "threaded through every node via `functools.partial` in `build_graph()`" | Exactly backwards. Copy `AGENTS.md:38`, which documents `RunnableConfig` / `nodes/runtime_config.py` and warns against reintroducing partials. |
| `CLAUDE.md:549`, `AGENTS.md:555` | "The graph is recompiled per request in the streaming endpoint" | Made false by §2. Rewrite for the shared module-level graph. |

**`recursion_limit` — ten occurrences of an API that does not exist.**
`CLAUDE.md:192, 209, 210, 431, 472` and `AGENTS.md:198, 215, 216, 437, 478`. Two are executable
examples (`graph.compile(checkpointer=checkpointer, recursion_limit=25)`), one is a reference-table
row naming `graph.compile()` as its home, two are checklist items instructing a reader to do it.

`compile()` accepts no `recursion_limit`. It is a **top-level runtime config key** passed to
`.invoke()` / `.stream()` — a sibling of `configurable`, explicitly not a member of it. The wrong
form raises `TypeError`; nesting it under `configurable` fails silently by being ignored. Correct
all ten to the config form. These files are loaded into every session's context by design, so this
is active instruction, not stale commentary.

**`OPENAI_MODEL` is documented as a tuning knob but cannot affect any node.**
`get_model` (`config.py:195-204`) only reaches `OPENAI_MODEL` via `fallback`, which applies when
`agent_key` is absent or missing from `AGENT_MODEL_NAMES`. Neither happens: `compose_final.py:158`,
`cross_check_facts.py:149`, and `generic_analyst.py:150` all pass keys present in the map, and
`llm.py:60`'s keyless call only fires when `StructuredOutputChain.model` is `None`, which no node
allows. `AGENT_MODEL_NAMES` is an eleven-key table where every value is `"gpt-4o-mini"`.

Amend both files to state that models are pinned per agent in `AGENT_MODEL_NAMES` and that
`OPENAI_MODEL` is not consulted by pipeline nodes. Do not change the code — model tiering is audit
§3.7 and out of scope.

> **Open — needs your call.** This last item is the one question from the brainstorm you did not
> answer (Q16). Applied here as the docs-only fix, matching the precedent set for `recursion_limit`.
> The alternative was a three-line precedence change in `get_model` making `OPENAI_MODEL` actually
> win, which was declined as a silent behavior change on any deploy with a stale value set.

---

## Known tightness (documented, not fixed)

The worst-case retry budget exceeds the frontend's own timeout.

- `frontend/index.html:473` hard-aborts at **10 minutes**.
- `DEFAULT_OPENAI_TIMEOUT_SECONDS = 60.0`, per attempt.
- `max_retries=2` means up to **3 attempts** per call.
- Sequential LLM depth is **4**: analyst main pass → analyst zero-claim retry
  (`generic_analyst.py:203`) → `cross_check_facts` → `compose_final`. Lanes run in parallel, so
  analysts contribute depth, not width. `build_research_plan` is deterministic and makes no call.

3 × 60s × 4 = 720s, plus roughly 80s of search, reaches **~13.3 minutes** against a 600s client
abort — the browser gives up while the server keeps working on a request nobody is listening to.

This is a tail bound, not an expected case: the common transient failure is a fast 429 or 5xx where
retries cost almost nothing and genuinely help. It is recorded here so the next person to touch
either number sees the constraint. Mitigating factor: these retries sit beneath the
`LLMInvocationError` boundary and the node fallbacks, so exhausting them produces a
degraded-but-complete run rather than a crash.

---

## Declined, with reasoning

**`recursion_limit` (audit §3.5).** Not added. `recursion_limit` caps supersteps; every edge in
`build_graph` is forward-only and the sole conditional edge picks between two forward branches.
Superstep count is fixed at **8** after §1 (ingest → plan → 4 searches in parallel → 4 analysts in
parallel → referee → cross_check_facts → compose_final → supervisor). Against a framework default of
25 the limit is structurally unreachable, not merely unlikely. The audit item came from a generic
checklist rather than analysis of this graph. The genuinely defective part — the documentation — is
fixed in §5.3.

**`checkpointer` parameter.** Removed rather than preserved. No caller supplies one: `cli.py:43`
does not pass it, both endpoints use the module-level graph, `langgraph.json` registers the
module-level graph, and `checkpointer` appears nowhere outside `graph.py`'s own signatures. v2 would
have kept a `run_pipeline` conditional whose second branch can never execute, for a capability the
same document declines to build. When checkpointing lands (audit §3.1) it brings its own design
questions — thread-id lifecycle, backend choice, how the API supplies `thread_id`, whether streaming
resumes — and the parameter gets re-added to fit those answers rather than these guesses.

**Polish loaded-language gate (audit §3.4).** Deferred to its own pass. `referee.LOADED_TERMS`
(`referee.py:9`) is ten English words, so the gate is inert for the `polish` infosphere — which is
the API's default. This is a real functional hole. The fix needs a language-keyed term table plus
threading `language` / `RunnableConfig` into `run_referee_checks`, which currently accepts neither.
Tracked separately to keep this pass bounded.

**TRUE-only synthesis gate.** Out of scope. `MISLEADING` is currently overloaded across three
unrelated conditions: a genuine adverse verdict, a fuzzy-match miss at the 0.85 `SequenceMatcher`
threshold (`cross_check_facts.py:20`), and — after §3.3 — a dead LLM call. All three funnel through
`compose_final`'s TRUE-only filter into the same canned "no TRUE claims" string. Splitting out an
`UNVERIFIED` verdict and permitting `PARTIALLY TRUE` with hedging would separate plumbing failure
from judgment. Deferred as an output-quality concern.

**No "before merging" checklist and no landing order.** Both removed at your direction. The
per-step "Tests and acceptance" subsections above are the acceptance criteria. Note for whoever
implements: `uv` is not installed on the current host and `geo_venv` has no `langgraph`, so
`make test` / `make lint` need an environment established first. CI additionally installs from the
stale root `requirements.txt` rather than `app/pyproject.toml`, so local and CI test different
dependency sets.

**`CLAUDE.md` / `AGENTS.md` divergence.** Observed, not addressed. The files are not duplicates —
157 diff lines — and have drifted one-directionally, with `AGENTS.md` updated during the `nodes/`
refactor and `CLAUDE.md` left behind. Nothing keeps them aligned, so every doc fix is done twice.
Full reconciliation, or collapsing to one canonical file with the other as a pointer, is a separate
decision.

**`report_mode` over HTTP.** Not exposed. Live for the CLI, absent over HTTP by design; see §5.2.

**Model tiering (audit §3.7).** Not changed. See §5.3 for the documentation fix and the open
question attached to it.
