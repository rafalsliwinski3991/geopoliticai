# Repo Cleanup Plan — 2026-08-24

**Based on:** [`docs/audits/2026Aug24_audit.md`](../audits/2026Aug24_audit.md), sections **3.2**, **3.3**, **3.6**, and **3.9** only. Everything else in the audit (checkpointing, recursion limits, model tiering, tracing, HITL, repo-root hygiene, etc.) is intentionally out of scope for this plan.

**Scope for this pass:**
1. §3.3 — `extract_claims`'s output is computed and stored but never read downstream.
2. §3.6 — the graph is rebuilt from scratch (`StateGraph(...)` → `add_node`/`add_edge` × 16 → `.compile()`) on every single API request.
3. §3.2 — error handling is inconsistent across nodes: some degrade gracefully, some silently propagate and kill the whole run.
4. §3.9 — SSE streaming only ever forwards node-start progress ticks; the user sees the entire final report appear as one blob instead of the final answer streaming in token-by-token.

All four live in `app/src/graph.py`, `app/src/api.py`, and `app/src/nodes/`. Ordered below so each step is independently mergeable and later steps build on earlier ones (§3.3 is pure deletion, §3.6 restructures how `api.py` owns the graph, §3.2 tightens node-level failure handling, §3.9 depends on §3.6's cached graph and rides on top of §3.2's already-established error-tagging pattern).

---

## 1. Remove the dead `extract_claims` node (§3.3)

`app/src/nodes/extract_claims.py` flattens every lane's claims into `state["extracted_claims"]` (with `stmt_type`, `asserted_by`, `confidence` fields). Nothing reads it: `cross_check_facts_agent` independently re-derives its own `claims` list from `state["left_claims"] + state["centrist_claims"] + state["right_claims"] + state["people_claims"]` (`app/src/nodes/cross_check_facts.py:119-124`), and `supervisor.py`/`compose_final.py` never touch `extracted_claims` either. It's a node that runs on every request, writes a field, and that field is dead weight from the moment it's written.

**Decision: delete it**, rather than wiring it up — nothing today needs `stmt_type`/`confidence`/`asserted_by`, and the project's own convention (see `CLAUDE.md`) is not to carry unused abstractions. If a future feature wants confidence-weighted fact-checking, it's a small node to re-add with a real consumer at the same time.

### 1.1 Drop the node and its edges from the graph

```diff
--- a/app/src/graph.py
+++ b/app/src/graph.py
@@
 from nodes import (
     build_research_plan_step,
     center_analyst_agent,
     compose_final_agent,
     cross_check_facts_agent,
-    extract_claims_for_verification,
     ingest_request,
     left_analyst_agent,
     people_analyst_agent,
     right_analyst_agent,
     run_referee_checks,
     search_center_pool,
     search_left_pool,
     search_people_pool,
     search_right_pool,
     summarize_referee_block,
     supervisor_step,
 )
@@
     graph.add_node("referee", run_referee_checks)
     graph.add_node("referee_blocked_summary", summarize_referee_block)
-    graph.add_node("extract_claims", extract_claims_for_verification)
     graph.add_node("cross_check_facts", cross_check_facts_agent)
     graph.add_node("compose_final", compose_final_agent)
     graph.add_node("supervisor", supervisor_step)
@@
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

### 1.2 Drop the now-unused state field

```diff
--- a/app/src/models.py
+++ b/app/src/models.py
@@ class PipelineState(TypedDict):
     research_plan: ResearchPlan
     referee_report: RefereeReport
-    extracted_claims: Annotated[list[dict[str, Any]], operator.add]
```

```diff
--- a/app/src/models.py
+++ b/app/src/models.py
@@ def build_initial_pipeline_state(
         "research_plan": ResearchPlan(),
         "referee_report": RefereeReport(),
-        "extracted_claims": [],
     }
```

### 1.3 Delete the file and its export

```bash
git rm app/src/nodes/extract_claims.py
```

```diff
--- a/app/src/nodes/__init__.py
+++ b/app/src/nodes/__init__.py
@@
 from nodes.compose_final import compose_final_agent
 from nodes.cross_check_facts import cross_check_facts_agent
-from nodes.extract_claims import extract_claims_for_verification
 from nodes.ingest_request import ingest_request
@@
 __all__ = [
     "build_research_plan_step",
     "center_analyst_agent",
     "compose_final_agent",
     "cross_check_facts_agent",
-    "extract_claims_for_verification",
     "ingest_request",
     "left_analyst_agent",
     "people_analyst_agent",
     "right_analyst_agent",
     "run_referee_checks",
     "search_center_pool",
     "search_left_pool",
     "search_people_pool",
     "search_right_pool",
     "summarize_referee_block",
     "supervisor_step",
 ]
```

### 1.4 Update the topology comment in `CLAUDE.md`

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@
 ingest_request → build_research_plan → ┬─ search_left_pool   → left_analyst    ─┐
                                        ├─ search_center_pool → center_analyst  ─┤
                                        ├─ search_right_pool  → right_analyst   ─┼→ referee ──(blocked)──→ referee_blocked_summary → supervisor → END
                                        └─ search_people_pool → people_analyst  ─┘                │
-                                                                                                 └──(continue)──→ extract_claims → cross_check_facts → compose_final → supervisor → END
+                                                                                                 └──(continue)──→ cross_check_facts → compose_final → supervisor → END
```

### 1.5 Checklist
- [ ] Remove `extract_claims` node + both its edges from `graph.py`, rewire `referee`'s `continue` branch straight to `cross_check_facts`
- [ ] Remove `extracted_claims` from `PipelineState` and `build_initial_pipeline_state`
- [ ] `git rm app/src/nodes/extract_claims.py`, drop its import/export in `nodes/__init__.py`
- [ ] Update the pipeline-shape diagram in `CLAUDE.md`
- [ ] Run `make test` — no test references `extracted_claims` today (confirmed by grep), so this should be a clean removal

---

## 2. Build the graph once instead of per-request (§3.6)

Today, `run_pipeline()` (used by the sync endpoint) and the SSE streaming endpoint both call `build_graph(infosphere=...)` **on every request** — a fresh `StateGraph(...)`, 16 `add_node`/`add_edge` calls, and a `.compile()`, all thrown away at the end of the request. This is safe to stop doing: every node already reads its per-request knobs (`language`, `infosphere_sources`, `report_mode`) from `RunnableConfig["configurable"]` (see `app/src/nodes/runtime_config.py`), not from closures baked in at build time — so the *same* compiled graph object can legitimately serve both `english` and `polish` requests. `report_mode` doesn't affect graph structure either (it's read at runtime by `supervisor_step`, not passed into `build_graph`'s node wiring), so caching only needs to be keyed by `infosphere`.

### 2.1 Split "build" from "invoke" in `graph.py`

`run_pipeline()` currently does both in one call, which is fine for the CLI (a fresh process per invocation) but wrong for a long-lived API process. Extract the invoke half so it can run against a graph built once elsewhere:

```diff
--- a/app/src/graph.py
+++ b/app/src/graph.py
@@ def build_graph(
     if checkpointer is None:
         return graph.compile(name="GeopoliticAI")
     return graph.compile(checkpointer=checkpointer, name="GeopoliticAI")


-def run_pipeline(
+def invoke_pipeline(
+    app: Any,
+    query: str,
+    infosphere: str = DEFAULT_INFOSPHERE,
+    report_mode: str = DEFAULT_REPORT_MODE,
+    *,
+    thread_id: str | None = None,
+) -> str:
+    """Execute an already-compiled graph and return the final rendered report."""
+    normalized_report_mode = _normalize_report_mode(report_mode)
+    language = normalize_language(infosphere)
+    initial_state = build_initial_pipeline_state(query, language=language)
+    config = build_runtime_config(
+        infosphere=infosphere,
+        report_mode=normalized_report_mode,
+        thread_id=thread_id,
+    )
+    result = app.invoke(initial_state, config=config)
+    return str(result["final_output"])
+
+
+def run_pipeline(
     query: str,
     infosphere: str = DEFAULT_INFOSPHERE,
     report_mode: str = DEFAULT_REPORT_MODE,
     *,
     thread_id: str | None = None,
     checkpointer: Any | None = None,
 ) -> str:
-    """Execute the pipeline and return the final rendered report."""
-    normalized_report_mode = _normalize_report_mode(report_mode)
-    language = normalize_language(infosphere)
-
+    """Build a fresh graph and execute it in one call — used by the CLI, where each
+    invocation is a new process and there's nothing to cache."""
     app = build_graph(
         infosphere=infosphere,
-        report_mode=normalized_report_mode,
+        report_mode=report_mode,
         checkpointer=checkpointer,
     )
-    initial_state = build_initial_pipeline_state(
-        query,
-        language=language,
-    )
-    config = build_runtime_config(
-        infosphere=infosphere,
-        report_mode=normalized_report_mode,
-        thread_id=thread_id,
-    )
-    result = app.invoke(initial_state, config=config)
-    return str(result["final_output"])
+    return invoke_pipeline(
+        app, query, infosphere=infosphere, report_mode=report_mode, thread_id=thread_id
+    )
```

`cli.py` needs no changes — `run_pipeline()` keeps its exact existing signature and behavior.

### 2.2 Build both language graphs once, at process startup, in `api.py`

```diff
--- a/app/src/api.py
+++ b/app/src/api.py
@@
 from collections import defaultdict, deque
 from contextlib import asynccontextmanager
 from threading import Lock
-from typing import AsyncGenerator, Literal
+from typing import Any, AsyncGenerator, Literal

 from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import FileResponse, StreamingResponse
 from fastapi.staticfiles import StaticFiles
 from pydantic import BaseModel, Field, field_validator

 import database
 from config import init_environment, require_env
-from graph import build_graph, build_runtime_config, run_pipeline
+from graph import build_graph, build_runtime_config, invoke_pipeline
 from models import build_initial_pipeline_state, normalize_language
@@
 _rate_limit_store: dict[str, deque[float]] = defaultdict(deque)
 _rate_limit_lock = Lock()
+
+# Built once at startup in `lifespan`; each compiled graph is reused across every
+# request for that infosphere, since per-request knobs flow through RunnableConfig
+# rather than through closures baked in at build time.
+_graphs: dict[str, Any] = {}
```

```diff
--- a/app/src/api.py
+++ b/app/src/api.py
@@ async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
     """Initialize and close optional application resources."""
     init_environment()
     require_env()
     db_url = os.getenv("DATABASE_URL")
     if db_url:
         await database.init_pool(db_url)
+    for infosphere in ("english", "polish"):
+        _graphs[infosphere] = build_graph(infosphere=infosphere)
     yield
+    _graphs.clear()
     await database.close_pool()
```

### 2.3 Use the cached graph in both endpoints

```diff
--- a/app/src/api.py
+++ b/app/src/api.py
@@ async def _generate() -> AsyncGenerator[str, None]:
         try:
-            graph = build_graph(infosphere=payload.infosphere)
+            graph = _graphs[payload.infosphere]
             initial_state = build_initial_pipeline_state(
                 payload.query,
                 language=normalize_language(payload.infosphere),
             )
             config = build_runtime_config(infosphere=payload.infosphere)
```

```diff
--- a/app/src/api.py
+++ b/app/src/api.py
@@ async def run_pipeline_endpoint(
     log_id = await database.log_prompt(payload.query, client_id)
     try:
-        output = run_pipeline(payload.query, infosphere=payload.infosphere)
+        graph = _graphs[payload.infosphere]
+        output = invoke_pipeline(graph, payload.query, infosphere=payload.infosphere)
     except ValueError as exc:
         raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Note: `RunPipelineRequest.infosphere` is a `Literal["english", "polish"]` validated by Pydantic before either endpoint body runs, so `_graphs[payload.infosphere]` can never `KeyError` — every valid request maps to a graph built at startup.

### 2.4 Checklist
- [ ] Split `graph.py`'s `run_pipeline` into `build_graph` + `invoke_pipeline`; keep `run_pipeline` as a thin CLI-only convenience wrapper
- [ ] Build `_graphs["english"]` / `_graphs["polish"]` once in `api.py`'s `lifespan`
- [ ] Swap both endpoints from `build_graph(...)`/`run_pipeline(...)` per-request to the cached `_graphs[payload.infosphere]`
- [ ] `make test` — `tests/integration_tests/test_graph.py` imports the module-level `graph` object directly and is unaffected

---

## 3. Consistent error handling across nodes (§3.2)

Right now, whether a transient failure degrades gracefully, kills the whole run, or is invisible outside the logs depends entirely on which node it happens to hit:

- `web_searcher` catches `httpx.HTTPError` per-domain (fine) but a missing `BRAVE_SEARCH_KEY` raises `ValueError`, uncaught, all the way up.
- `cross_check_facts_agent` has **no** try/except around its LLM call — one OpenAI timeout there kills a run that already did 8 successful upstream searches + analyst calls.
- `compose_final_agent` **does** catch `Exception` and degrade to a deterministic fallback string — but silently (`logger.warning` only), with no trace left in state or in the API response.
- `run_pipeline_endpoint` only catches `ValueError`; anything else becomes a bare unhandled 500.

Fix in three parts: a graph-level retry policy for the transient case, a typed error trail in state for the non-transient case, and a proper HTTP status for what's left.

### 3.1 Add a `RetryPolicy` to every network/LLM-calling node

```diff
--- a/app/src/graph.py
+++ b/app/src/graph.py
@@
 from langgraph.graph import END, START, StateGraph
+from langgraph.types import RetryPolicy

 from config import get_infosphere_sources
@@
 DEFAULT_INFOSPHERE = "english"
 DEFAULT_REPORT_MODE = "full"
+
+# Brave Search calls are cheap to retry aggressively; LLM calls are not.
+SEARCH_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0)
+LLM_RETRY = RetryPolicy(max_attempts=2, initial_interval=2.0, backoff_factor=2.0)
```

```diff
--- a/app/src/graph.py
+++ b/app/src/graph.py
@@ def build_graph(
     graph.add_node("ingest_request", ingest_request)
     graph.add_node("build_research_plan", build_research_plan_step)
-    graph.add_node("search_left_pool", search_left_pool)
-    graph.add_node("search_center_pool", search_center_pool)
-    graph.add_node("search_right_pool", search_right_pool)
-    graph.add_node("search_people_pool", search_people_pool)
-    graph.add_node("left_analyst", left_analyst_agent)
-    graph.add_node("center_analyst", center_analyst_agent)
-    graph.add_node("right_analyst", right_analyst_agent)
-    graph.add_node("people_analyst", people_analyst_agent)
+    graph.add_node("search_left_pool", search_left_pool, retry_policy=SEARCH_RETRY)
+    graph.add_node("search_center_pool", search_center_pool, retry_policy=SEARCH_RETRY)
+    graph.add_node("search_right_pool", search_right_pool, retry_policy=SEARCH_RETRY)
+    graph.add_node("search_people_pool", search_people_pool, retry_policy=SEARCH_RETRY)
+    graph.add_node("left_analyst", left_analyst_agent, retry_policy=LLM_RETRY)
+    graph.add_node("center_analyst", center_analyst_agent, retry_policy=LLM_RETRY)
+    graph.add_node("right_analyst", right_analyst_agent, retry_policy=LLM_RETRY)
+    graph.add_node("people_analyst", people_analyst_agent, retry_policy=LLM_RETRY)
     graph.add_node("referee", run_referee_checks)
     graph.add_node("referee_blocked_summary", summarize_referee_block)
-    graph.add_node("cross_check_facts", cross_check_facts_agent)
-    graph.add_node("compose_final", compose_final_agent)
+    graph.add_node("cross_check_facts", cross_check_facts_agent, retry_policy=LLM_RETRY)
+    graph.add_node("compose_final", compose_final_agent, retry_policy=LLM_RETRY)
     graph.add_node("supervisor", supervisor_step)
```

This alone fixes the "one OpenAI hiccup in `cross_check_facts` kills the entire run" case at the framework level — LangGraph will re-run that single node up to `max_attempts` times before the exception ever reaches user code.

### 3.2 Add a typed error trail to state

```diff
--- a/app/src/models.py
+++ b/app/src/models.py
@@ class RefereeReport:
     unsupported_facts: list[str] = field(default_factory=list)
     loaded_language: list[str] = field(default_factory=list)


+class ErrorRecord(TypedDict):
+    """A single node-level failure surfaced into pipeline state."""
+
+    node: str
+    error_type: str
+    message: str
+
+
 class PipelineState(TypedDict):
     """LangGraph state shared by all pipeline nodes."""
@@
     research_plan: ResearchPlan
     referee_report: RefereeReport
+    errors: Annotated[list[ErrorRecord], operator.add]
```

```diff
--- a/app/src/models.py
+++ b/app/src/models.py
@@ def build_initial_pipeline_state(
         "research_plan": ResearchPlan(),
         "referee_report": RefereeReport(),
+        "errors": [],
     }
```

### 3.3 Give `cross_check_facts` the same graceful-degradation try/except `compose_final` already has

If retries in 3.1 are exhausted, `cross_check_facts` should degrade to "no verdicts" rather than take the whole pipeline down — `compose_final`'s existing `_fallback_for_no_true_claims` path already handles "zero verified claims" correctly, so failing into it is free:

```diff
--- a/app/src/nodes/cross_check_facts.py
+++ b/app/src/nodes/cross_check_facts.py
@@
     response_language = "Polish" if language == "polish" else "English"
     model_name = get_model("cross_check_facts")

-    data = invoke_structured_chain(
-        schema=FactCheckOutput,
-        system_prompt="You are a meticulous fact-checker who only uses the provided sources.",
-        human_prompt=(
-            ...
-        ),
-        variables={...},
-        temperature=0.0,
-        model=model_name,
-    )
+    try:
+        data = invoke_structured_chain(
+            schema=FactCheckOutput,
+            system_prompt="You are a meticulous fact-checker who only uses the provided sources.",
+            human_prompt=(
+                ...
+            ),
+            variables={...},
+            temperature=0.0,
+            model=model_name,
+        )
+    except Exception as exc:
+        logger.warning(
+            "Cross-check facts: LLM call failed after retries, returning no verdicts: %s",
+            exc,
+        )
+        return {
+            "fact_sources": fact_sources,
+            "fact_checks": [],
+            "errors": [
+                {
+                    "node": "cross_check_facts",
+                    "error_type": type(exc).__name__,
+                    "message": str(exc),
+                }
+            ],
+        }
```

(`...` above stands for the existing prompt body — unchanged, just now wrapped.)

### 3.4 Tag `compose_final`'s existing fallback with the same error record

```diff
--- a/app/src/nodes/compose_final.py
+++ b/app/src/nodes/compose_final.py
@@
     except Exception as exc:
         logger.warning("Compose final: LLM synthesis failed, using fallback: %s", exc)
-        return {"synthesis": _fallback_from_true_claims(true_claims, language)}
+        return {
+            "synthesis": _fallback_from_true_claims(true_claims, language),
+            "errors": [
+                {
+                    "node": "compose_final",
+                    "error_type": type(exc).__name__,
+                    "message": str(exc),
+                }
+            ],
+        }
```

### 3.5 Surface degraded runs in the rendered report

`state["errors"]` now exists but nothing shows it to the caller. `supervisor.py` already logs claim/verdict counts every run — add one line when `errors` is non-empty, in both report modes, so a degraded-but-not-crashed run is visible instead of looking identical to a clean one:

```diff
--- a/app/src/nodes/compose_final.py
+++ b/app/src/nodes/compose_final.py
```
_(rendering lives in `supervisor.py`, not `compose_final.py` — see below)_

```diff
--- a/app/src/nodes/supervisor.py
+++ b/app/src/nodes/supervisor.py
@@ def supervisor_step(state: PipelineState) -> dict[str, Any]:
         lines.append(f"{question_label} {state['query']}")
         lines.append("")
         lines.append(f"{answer_label} {short_answer}")
         lines.append("")
+
+        errors = state.get("errors") or []
+        if errors:
+            degraded_note = (
+                f"(Uwaga: {len(errors)} etap(y) pipeline'u napotkały błąd i użyły wyniku zastępczego.)"
+                if language == "polish"
+                else f"(Note: {len(errors)} pipeline step(s) hit an error and used a fallback result.)"
+            )
+            lines.append(degraded_note)
+            lines.append("")
```

### 3.6 Broaden the sync endpoint's exception handling

```diff
--- a/app/src/api.py
+++ b/app/src/api.py
@@ async def run_pipeline_endpoint(
     try:
         graph = _graphs[payload.infosphere]
         output = invoke_pipeline(graph, payload.query, infosphere=payload.infosphere)
     except ValueError as exc:
         raise HTTPException(status_code=400, detail=str(exc)) from exc
+    except Exception as exc:
+        logger.exception("Pipeline run failed unexpectedly.")
+        raise HTTPException(
+            status_code=502, detail="Analysis failed upstream; please retry."
+        ) from exc
     if log_id is not None:
         background_tasks.add_task(database.log_output, log_id, output)
     return RunPipelineResponse(output=_sanitize_output(output))
```

(The streaming endpoint's `_generate()` already has a catch-all `except Exception` that emits an `{"type": "error", ...}` SSE event, so it needs no change here.)

### 3.7 Checklist
- [ ] `SEARCH_RETRY` / `LLM_RETRY` `RetryPolicy`s on all 8 network/LLM nodes in `graph.py`
- [ ] `ErrorRecord` + `errors: Annotated[list[ErrorRecord], operator.add]` on `PipelineState`
- [ ] Wrap `cross_check_facts_agent`'s LLM call in try/except, degrading like `compose_final` already does
- [ ] Tag `compose_final`'s existing except-block with an `errors` entry
- [ ] Surface a one-line "degraded run" note in `supervisor.py` when `state["errors"]` is non-empty
- [ ] `except Exception` → `HTTPException(502, ...)` in `run_pipeline_endpoint`
- [ ] New unit test: force `invoke_structured_chain` to raise inside `cross_check_facts_agent`, assert the node returns `fact_checks: []` + a populated `errors` list instead of propagating

---

## 4. Token-level streaming for the final answer (§3.9)

The SSE stream today only ever forwards `on_chain_start` (for the "Analyzing left perspective..." progress ticks) and the graph's final `on_chain_end` — the user sees ~10 static progress lines and then the entire final report appears as one blob. `compose_final` is exactly the node whose output is user-facing prose and should stream.

**The catch:** `compose_final_agent` currently calls the LLM through `invoke_structured_chain(schema=SynthesisOutput, ...)`, i.e. `ChatOpenAI(...).with_structured_output(SynthesisOutput)`. Structured-output calls stream their payload as incremental **tool-call/JSON deltas**, not as plain `.content` text chunks — forwarding `on_chat_model_stream` for this node as-is would either yield nothing useful or dribble out raw `{"synthesis": "Sho` JSON fragments, which is worse than not streaming at all.

`SynthesisOutput` is a single-string-field schema whose only real job today is turning the model's answer into `{"synthesis": "..."}\` — there's nothing structural being extracted. So: switch `compose_final` to a **plain text completion** (no `with_structured_output`), which both unlocks clean token streaming and removes a schema that was buying nothing. This also deletes the `_coerce_synthesis_to_text` validator, which existed specifically to paper over structured-output edge cases (dict/list payloads) that a plain-text call can't produce in the first place.

### 4.1 Add a plain-text (streamable) chain helper next to the existing structured one

```diff
--- a/app/src/llm.py
+++ b/app/src/llm.py
@@ def invoke_structured_chain(
     return chain.invoke(variables)
+
+
+@dataclass
+class TextOutputChain:
+    """Prompt + plain-text chain — unlike StructuredOutputChain, this streams real
+    content tokens via astream_events, since there's no tool-call/JSON wrapping."""
+
+    system_prompt: str
+    human_prompt: str
+    temperature: float = 0.0
+    model: str | None = None
+
+    def invoke(self, variables: dict[str, Any]) -> str:
+        model = self.model or get_model()
+        prompt = ChatPromptTemplate.from_messages(
+            [
+                ("system", self.system_prompt),
+                ("human", self.human_prompt),
+            ]
+        )
+        llm = ChatOpenAI(
+            model=model,
+            temperature=self.temperature,
+            max_completion_tokens=get_openai_max_output_tokens(),
+            timeout=get_openai_timeout_seconds(),
+        )
+        result = (prompt | llm).invoke(variables)
+        return str(result.content)
+
+
+def invoke_text_chain(
+    *,
+    system_prompt: str,
+    human_prompt: str,
+    variables: dict[str, Any],
+    temperature: float = 0.0,
+    model: str | None = None,
+) -> str:
+    """Invoke a one-shot plain-text chain. Prefer this over invoke_structured_chain
+    whenever the desired output is just prose — it streams; structured JSON doesn't."""
+    chain = TextOutputChain(
+        system_prompt=system_prompt,
+        human_prompt=human_prompt,
+        temperature=temperature,
+        model=model,
+    )
+    return chain.invoke(variables)
```

### 4.2 Switch `compose_final` to the plain-text chain

```diff
--- a/app/src/nodes/compose_final.py
+++ b/app/src/nodes/compose_final.py
@@
-import json
 import logging
-from typing import Any, cast
+from typing import Any

 from langchain_core.runnables import RunnableConfig
-from pydantic import BaseModel, field_validator

 from config import get_model
-from llm import invoke_structured_chain
+from llm import invoke_text_chain
 from models import Claim, PipelineState
 from nodes.runtime_config import runtime_language

 logger = logging.getLogger(__name__)


-class SynthesisOutput(BaseModel):
-    """Structured output for final synthesis."""
-
-    synthesis: str = ""
-
-    @field_validator("synthesis", mode="before")
-    @classmethod
-    def _coerce_synthesis_to_text(cls, value: Any) -> str:
-        """Normalize non-string synthesis payloads into text."""
-        if isinstance(value, str):
-            return value
-        if isinstance(value, dict):
-            lines: list[str] = []
-            for key, nested in value.items():
-                label = key.replace("_", " ").strip().capitalize()
-                if isinstance(nested, str):
-                    lines.append(f"{label}: {nested}")
-                else:
-                    lines.append(f"{label}: {json.dumps(nested, ensure_ascii=False)}")
-            return "\n".join(lines)
-        if isinstance(value, list):
-            return "\n".join(str(item) for item in value)
-        return str(value)
-
-
 def _all_claims(state: PipelineState) -> list[Claim]:
```

```diff
--- a/app/src/nodes/compose_final.py
+++ b/app/src/nodes/compose_final.py
@@ def compose_final_agent(
     try:
-        data = invoke_structured_chain(
-            schema=SynthesisOutput,
+        synthesis_text = invoke_text_chain(
             system_prompt=(
                 "You are a precise final-answer agent. "
                 "Use only TRUE-verified claims provided by the pipeline."
             ),
             human_prompt=(
                 "User query: {query}\n\n"
                 "TRUE-verified claims:\n{true_claims_block}\n\n"
                 "Task: Answer the user query directly using only the TRUE-verified claims above.\n"
                 "Requirements:\n"
                 "- Write in {response_language}.\n"
                 "- First line must be: 'Short answer: ...'.\n"
                 "- Do not use claims that are not in the TRUE list.\n"
                 "- Include source IDs in the rationale when available.\n"
                 "- If the TRUE claims are still insufficient for a precise answer, explicitly say so.\n"
-                "Return JSON with exactly one key: synthesis (string)."
+                "Respond with plain prose only — no JSON, no markdown code fences."
             ),
             variables={
                 "query": state["query"],
                 "true_claims_block": true_claims_block,
                 "response_language": response_language,
             },
             temperature=0.0,
             model=model_name,
         )
     except Exception as exc:
         logger.warning("Compose final: LLM synthesis failed, using fallback: %s", exc)
         return {
             "synthesis": _fallback_from_true_claims(true_claims, language),
             "errors": [
                 {
                     "node": "compose_final",
                     "error_type": type(exc).__name__,
                     "message": str(exc),
                 }
             ],
         }
-    synthesis_data = cast(SynthesisOutput, data)
-    synthesis = _ensure_short_answer_prefix(synthesis_data.synthesis.strip(), language)
-
+    synthesis = _ensure_short_answer_prefix(synthesis_text.strip(), language)
     return {"synthesis": synthesis}
```

_(The `except Exception` block shown here already includes the `errors` tagging from §3, step 3.4 — apply that step first if doing both in one pass.)_

### 4.3 Forward `compose_final`'s tokens as their own SSE event

```diff
--- a/app/src/api.py
+++ b/app/src/api.py
@@ async def _generate() -> AsyncGenerator[str, None]:
             async for event in graph.astream_events(
                 initial_state, config=config, version="v2"
             ):
                 etype = event.get("event", "")
                 node = event.get("metadata", {}).get("langgraph_node", "")

                 if (
                     etype == "on_chain_start"
                     and node in node_labels
                     and node not in seen_nodes
                 ):
                     seen_nodes.add(node)
                     data = json.dumps(
                         {
                             "type": "progress",
                             "node": node,
                             "label": node_labels[node],
                         }
                     )
                     yield f"data: {data}\n\n"

+                if etype == "on_chat_model_stream" and node == "compose_final":
+                    chunk = event.get("data", {}).get("chunk")
+                    token = getattr(chunk, "content", "") if chunk is not None else ""
+                    if token:
+                        data = json.dumps({"type": "token", "content": token})
+                        yield f"data: {data}\n\n"
+
                 if etype == "on_chain_end" and event.get("name") == "GeopoliticAI":
                     output = event.get("data", {}).get("output", {})
                     if isinstance(output, dict):
                         final_output = output.get("final_output")
```

The final `"result"` event is unchanged and still carries the fully-rendered report (per-lane claims, fact-check summary, sources — everything `supervisor.py` assembles, not just the raw synthesis prose). Token events are a **live preview of the answer while it's being written**, not a replacement for the final formatted message.

### 4.4 Consume the new event in the frontend

```diff
--- a/frontend/index.html
+++ b/frontend/index.html
@@
           progressLog: [],
+          streamingDraft: "",
           messages: [],
```

```diff
--- a/frontend/index.html
+++ b/frontend/index.html
@@
                     const data = JSON.parse(line.slice(6));
                     if (data.type === "progress") {
                       this.progressLog.push(data);
                       this.scrollToBottom();
+                    } else if (data.type === "token") {
+                      this.streamingDraft += data.content;
+                      this.scrollToBottom();
                     } else if (data.type === "result") {
                       this.progressLog = [];
+                      this.streamingDraft = "";
                       this.messages.push({ role: "bot", text: data.output, timestamp: new Date() });
                       this.scrollToBottom();
                     } else if (data.type === "error") {
                       this.progressLog = [];
+                      this.streamingDraft = "";
                       this.messages.push({ role: "error", text: data.message, timestamp: new Date() });
                       this.scrollToBottom();
                     }
```

Render `streamingDraft` as a live-updating bubble near the existing `progress-log` block (markup omitted here — same pattern as the existing `x-show="progressLog.length > 0"` block, `x-show="streamingDraft.length > 0"`, `x-text="streamingDraft"`). It gets cleared the moment the final `"result"`/`"error"` event lands, exactly like `progressLog` already does.

### 4.5 Checklist
- [ ] Add `TextOutputChain`/`invoke_text_chain` to `llm.py`
- [ ] Switch `compose_final_agent` from `invoke_structured_chain(schema=SynthesisOutput, ...)` to `invoke_text_chain(...)`; delete `SynthesisOutput` and its validator
- [ ] Forward `on_chat_model_stream` events scoped to `node == "compose_final"` as `{"type": "token", "content": ...}` SSE events in `api.py`
- [ ] Add a `streamingDraft` bubble to the frontend, cleared on `result`/`error`
- [ ] Manually verify in a browser: tokens visibly accumulate before the final formatted report replaces them
- [ ] Update existing `compose_final` unit tests (if any mock `invoke_structured_chain`) to mock `invoke_text_chain` returning a plain string instead of a `SynthesisOutput` instance

---

## Suggested landing order

| Step | Touches | Depends on |
|---|---|---|
| 1. Remove `extract_claims` | `graph.py`, `models.py`, `nodes/` | — |
| 2. Build graph once | `graph.py`, `api.py` | — (independent of 1, but do first since 3–4 both edit `api.py`/`graph.py`) |
| 3. Error handling | `graph.py`, `models.py`, `nodes/cross_check_facts.py`, `nodes/compose_final.py`, `nodes/supervisor.py`, `api.py` | Step 2 (touches the same `api.py` exception block) |
| 4. Token streaming | `llm.py`, `nodes/compose_final.py`, `api.py`, `frontend/index.html` | Step 3 (reuses the `errors`-tagging pattern already added to `compose_final`'s except-block) |

Steps 1 and 2 can ship in either order or together as one PR. Land 3 before 4 — 4's diff to `compose_final.py` assumes the try/except shape 3 already put in place.
