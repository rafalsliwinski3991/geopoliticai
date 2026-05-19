# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Keep this file in sync with the codebase.** After any significant change (e.g., new agent nodes, API route changes, env var additions, architecture shifts), update the relevant section here so future Claude instances have accurate context.

## Project layout

The live code lives under `app/`. The shipped image is built from `app/Dockerfile`, and the CLI/API entrypoints are in `app/src/`.

- `app/src/` — Python package; treated as the import root (`PYTHONPATH=/app/src` in containers). Modules use bare `from agents import ...`, `from models import ...` style, so the package directory must be on `sys.path`.
- `frontend/` — single `index.html` (Alpine.js + `marked.js` from CDN) plus `assets/`. No bundler. Served either directly by FastAPI (dev) or by nginx (prod).
- `docker-compose.yml` + `docker-compose.override.yml` — local dev. The override mounts `app/src` and `frontend/` into the backend container, exposes port `3000:8000`, and runs uvicorn with `--reload`. The frontend container is gated behind the `production` profile, so `docker compose up` runs only postgres + backend.
- `docker-compose.prod.yml` — adds restart policies, the `/api/health` healthcheck, TLS cert mount (`/etc/letsencrypt`), and basic-auth env vars; activates the frontend service.
- `app/langgraph.json` — registers `src/graph.py:graph` for LangGraph Studio (`langgraph dev`).

## Architecture

A multi-agent political analysis pipeline built on **LangGraph** (`StateGraph` over a `PipelineState` TypedDict) and **FastAPI**. The single source of truth for the flow is `app/src/graph.py`.

Pipeline shape (fan-out → converge → fact-check → compose):

```
ingest_request → build_research_plan → ┬─ search_left_pool   → left_analyst    ─┐
                                       ├─ search_center_pool → center_analyst  ─┤
                                       ├─ search_right_pool  → right_analyst   ─┼→ referee ──(blocked)──→ referee_blocked_summary → supervisor → END
                                       └─ search_people_pool → people_analyst  ─┘                │
                                                                                                 └──(continue)──→ extract_claims → cross_check_facts → compose_final → supervisor → END
```

- **Lanes** (`left`, `centrist`, `right`, `people`, plus `fact` for cross-checking): each lane has a curated source allow-list per infosphere defined in `app/src/config.py` (`ENGLISH_INFOSPHERE_SOURCES`, `POLISH_INFOSPHERE_SOURCES`). Search queries are constrained with `site:` filters built from those domains.
- **Infosphere** (`"english"` | `"polish"`): selected explicitly via the `--infosphere` CLI flag or the `infosphere` field in API requests. CLI auto-detects via `detect_language()` in `models.py` (Polish diacritics + stopword tokens). The infosphere drives both source pools and prompt language.
- **Referee** can short-circuit the pipeline (returns `blocked: true`), routing through `referee_blocked_summary` instead of fact-checking.
- **`compose_final`** writes the user-facing report; **`supervisor`** is the terminal node that emits `final_output`.
- **OpenAI calls** go through `app/src/llm.py`, which wraps both the Responses API and Chat Completions with JSON-mode output and graceful retries for `max_completion_tokens`/`temperature` compatibility issues across model variants. All structured outputs use `StructuredOutputChain` (Pydantic schema → JSON object).
- **Search** (`app/src/search.py`) calls Brave Search, restricted to lane-allowed domains; results are renumbered with lane-prefixed source IDs (`L1`, `C1`, `R1`, `P1`, `F1`).
- **Persistence**: `app/src/database.py` is an optional asyncpg pool that logs prompts and outputs into a `prompt_logs` table. Activated only when `DATABASE_URL` is set; otherwise log calls become no-ops. The pool is initialised in the FastAPI `lifespan` hook.
- **API**: `app/src/api.py` exposes `POST /api/run_pipeline` (sync) and `POST /api/run_pipeline/stream` (SSE with per-node progress events). Both enforce an in-process token-bucket rate limit keyed by `X-Forwarded-For` (or `request.client.host`). The streaming endpoint uses `graph.astream_events(version="v2")` and emits Polish or English progress labels based on the request's `infosphere`.
- **Frontend integration**: in dev, FastAPI mounts `/assets` and serves `frontend/index.html` at `/` via `FileResponse` (paths controlled by `FRONTEND_HTML_PATH`). In prod, nginx serves the static frontend and proxies `/api/` to the backend. `frontend/nginx.conf` is the prod config (TLS + basic auth via `docker-entrypoint.sh` writing `htpasswd`).


## LangGraph Agentic Workflows — Best Practices

> Reference guide for building sophisticated, production-grade agentic systems with LangGraph.

---

## 1. State Design

State is the **single source of truth** for the entire graph. Design it carefully — it is effectively the public API of your workflow.

### Rules
- Use `TypedDict` internally for all graph state. Use Pydantic **only** at external boundaries (API input/output validation).
- Keep state **flat**. Avoid deeply nested dicts — they are harder to merge, serialize, and debug.
- Every field must have a clear owner and a documented purpose. Undocumented fields accumulate fast.
- Use `Annotated` + reducers for any field that accumulates values across nodes (lists, counters, logs).
- Never store large blobs (raw file bytes, huge DataFrames) in state. Store references (paths, IDs, URIs) instead.

```python
from typing import Annotated
from typing_extensions import TypedDict
from operator import add

class AgentState(TypedDict):
    messages: Annotated[list, add]        # accumulates — uses add reducer
    tool_results: Annotated[list, add]    # accumulates
    status: str                           # overwrites — no reducer needed
    error_count: Annotated[int, add]      # accumulates errors
    final_answer: str | None              # overwrites
```

### Memory scopes

| Scope | Mechanism | Lifetime | Use case |
|---|---|---|---|
| **Short-term** | `MessagesState` + checkpointer | Single thread/session | Conversation history, intermediate results |
| **Long-term** | `InMemoryStore` / `PostgresStore` + `get_store()` | Cross-thread, persistent | User preferences, learned facts, profile data |
| **Working** | Custom state fields | Single graph run | Intermediate computations, scratch pad |
| **Semantic** | Vector store + retrieval tool | Persistent | Knowledge base, episodic recall |

```python
# Long-term memory — always use get_store() inside nodes, not outer scope
from langgraph.store.memory import get_store

def remember_node(state: AgentState) -> dict:
    store = get_store()  # injected by LangGraph runtime
    ns = ("users", state["user_id"], "preferences")
    store.put(ns, "profile", {"tone": "formal", "language": "pl"})
    return {}
```

---

## 2. Node Design

Each node is a pure-ish Python function. Treat it like a **microservice**: single responsibility, independently testable, no hidden side effects on external mutable state.

### Rules
- One node = one responsibility. If a node does two things, split it.
- Nodes must return a **dict** (partial state update), never mutate state in-place.
- Keep routing logic **out of nodes** — use conditional edges instead.
- Differentiate retry policies: LLM nodes are expensive → conservative retry; Tool nodes are cheap → aggressive retry.

```python
from langgraph.graph import RetryPolicy

llm_retry = RetryPolicy(max_attempts=3, backoff_factor=2.0)   # conservative
api_retry = RetryPolicy(max_attempts=5, backoff_factor=0.5)   # aggressive

builder.add_node("agent",  agent_node,  retry=llm_retry)
builder.add_node("tools",  tool_node,   retry=api_retry)
builder.add_node("validate", validate_node)  # no retry — errors here are user-fixable
```

### Node types reference

| Type | Purpose | Built-in? |
|---|---|---|
| **LLM Node** | Calls the language model, generates next action or response | ❌ custom |
| **ToolNode** | Executes tool calls returned by the LLM | ✅ `from langgraph.prebuilt import ToolNode` |
| **Router Node** | Reads state, returns next node name (used with conditional edges) | ❌ custom |
| **Human-in-the-Loop Node** | Pauses execution with `interrupt()`, waits for external input | ❌ custom using `interrupt()` |
| **Subgraph Node** | Embeds a compiled child graph as a single node | ✅ via `graph.add_node("name", compiled_subgraph)` |
| **Error Handler Node** | Catches and categorizes errors, routes to fallback or escalation | ❌ custom |

---

## 3. Edges and Routing

Routing logic belongs in **conditional edges**, not inside node bodies. This keeps the graph's control flow readable at a glance.

```python
from langgraph.graph import END

def route_after_llm(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    if state["error_count"] > 3:
        return "error_handler"
    return END

graph.add_conditional_edges(
    "agent",
    route_after_llm,
    {"tools": "tools", "error_handler": "error_handler", END: END}
)
```

### Retry loops — always cap iterations

```python
MAX_RETRIES = 5

def should_retry(state: AgentState) -> str:
    if state["error_count"] >= MAX_RETRIES:
        return "fallback"
    return "agent"

graph.add_conditional_edges("error_handler", should_retry)
```

---

## 4. Error Handling

Errors should be **first-class citizens in state** — typed, tracked, routable.

```python
from typing import TypedDict

class ErrorRecord(TypedDict):
    node: str
    error_type: str
    message: str
    timestamp: str

class AgentState(TypedDict):
    messages: Annotated[list, add]
    errors: Annotated[list[ErrorRecord], add]  # accumulate all errors
    error_count: Annotated[int, add]
```

### Multi-level error strategy

| Level | Mechanism | Action |
|---|---|---|
| **Node-level** | `try/except` inside node | Add to `errors` state, increment counter, continue |
| **Graph-level** | Conditional edge on `error_count` | Route to fallback or error_handler node |
| **Application-level** | Wrap `graph.invoke()` | Handle `GraphInterruptException`, timeouts, unrecoverable failures |
| **Guardrails** | `recursion_limit` in `graph.compile()` | Prevent infinite loops — set explicitly |

```python
import traceback
from datetime import datetime

def safe_tool_node(state: AgentState) -> dict:
    try:
        result = run_tool(state)
        return {"tool_results": [result]}
    except Exception as e:
        return {
            "errors": [{"node": "tool_node", "error_type": type(e).__name__,
                        "message": str(e), "timestamp": datetime.utcnow().isoformat()}],
            "error_count": 1
        }

# Set recursion_limit to avoid runaway loops
app = graph.compile(checkpointer=checkpointer, recursion_limit=25)
```

---

## 5. Checkpointing and Persistence

Checkpointers are mandatory for production. They provide:
- **Fault tolerance** — resume after crash from last super-step
- **Human-in-the-loop** — pause and resume workflow
- **Time-travel debugging** — replay from any historical checkpoint
- **Concurrency safety** — isolated threads per conversation

```python
# Development
from langgraph.checkpoint.memory import InMemorySaver
checkpointer = InMemorySaver()

# Production — use persistent backends
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)

app = graph.compile(checkpointer=checkpointer)

# Always pass thread_id for isolation
config = {"configurable": {"thread_id": "user-123-session-456"}}
result = app.invoke({"messages": [HumanMessage(content="...")]}, config=config)
```

### Checkpoint backends

| Backend | Use case |
|---|---|
| `InMemorySaver` | Local development only |
| `PostgresSaver` | Production — durable, queryable |
| `RedisSaver` | High-throughput, short-lived sessions |
| `SqliteSaver` | Lightweight local/testing |

---

## 6. Human-in-the-Loop (HITL)

Use `interrupt()` to pause graph execution for human review. LangGraph saves state to checkpoint automatically — resume is seamless.

```python
from langgraph.types import interrupt, Command

def human_approval_node(state: AgentState) -> dict:
    # Execution pauses here — state is saved to checkpointer
    decision = interrupt({
        "question": "Approve this action?",
        "planned_action": state["planned_action"],
        "risk_level": state["risk_assessment"]
    })
    return {"approved": decision == "approve", "human_feedback": decision}

# Resume after human input
app.invoke(Command(resume="approve"), config=config)
```

### HITL patterns

| Pattern | When to use |
|---|---|
| **Approval gate** | Before destructive actions (delete, send email, execute payment) |
| **Feedback loop** | Agent output needs human rating before proceeding |
| **Clarification** | Agent is uncertain — ask human instead of guessing |
| **Escalation** | `error_count` exceeded — escalate to human operator |

---

## 7. Multi-Agent Architecture

### Supervisor + Subagents

The supervisor routes tasks to specialist subagents. Each subagent is a compiled subgraph. Supervisor maintains global state; subagents are stateless from the perspective of the parent.

```python
from langgraph.prebuilt import create_react_agent

# Specialist subagents
research_agent = create_react_agent(llm, tools=[web_search, arxiv_search])
code_agent     = create_react_agent(llm, tools=[run_python, read_file, write_file])
data_agent     = create_react_agent(llm, tools=[query_db, run_sql])

def supervisor_node(state: SupervisorState) -> dict:
    response = supervisor_llm.invoke(state["messages"])
    return {"messages": [response], "next": response.content}

def route_to_agent(state: SupervisorState) -> str:
    return {"research": "research_agent", "code": "code_agent",
            "data": "data_agent", "FINISH": END}.get(state["next"], END)

builder.add_node("supervisor",      supervisor_node)
builder.add_node("research_agent",  research_agent)
builder.add_node("code_agent",      code_agent)
builder.add_node("data_agent",      data_agent)

builder.add_conditional_edges("supervisor", route_to_agent)
# All agents return to supervisor
for agent in ["research_agent", "code_agent", "data_agent"]:
    builder.add_edge(agent, "supervisor")
```

### Custom handoffs — pass explicit context

Never let the supervisor hand off control without passing explicit instructions. Generic handoffs cause subagent drift.

```python
# BAD — subagent receives no guidance
Command(goto="research_agent")

# GOOD — subagent knows exactly what to do
Command(
    goto="research_agent",
    update={"task": "Find Q1 2025 revenue data for NVIDIA", "format": "table", "depth": "detailed"}
)
```

### When to use subgraphs

- Logic that is **reused** across multiple parent graphs
- Teams that need to **develop independently** (separate repos/owners)
- Complex sub-workflows that benefit from their own internal state schema
- **Parallel fan-out** — use `Send` API to spawn dynamic instances of a subgraph

---

## 8. Parallelism — Fan-Out / Fan-In

Use the `Send` API for dynamic parallel execution (map-reduce pattern). This is the LangGraph-native way, not imperative loops.

```python
from langgraph.types import Send

def fan_out_node(state: AgentState) -> list[Send]:
    # Spawn one worker per task — all run in parallel in the next super-step
    return [Send("worker_node", {"task": t, "context": state["context"]})
            for t in state["tasks"]]

def worker_node(state: WorkerState) -> dict:
    result = process(state["task"])
    return {"results": [result]}  # reducer accumulates

def fan_in_node(state: AgentState) -> dict:
    summary = aggregate(state["results"])
    return {"final_answer": summary}

builder.add_node("fan_out",  fan_out_node)
builder.add_node("worker",   worker_node)
builder.add_node("fan_in",   fan_in_node)

builder.add_conditional_edges("fan_out", lambda s: s, ["worker"])
builder.add_edge("worker", "fan_in")
```

**Rules for parallelism:**
- Always use `Annotated[list, add]` reducers for fields that collect parallel results.
- Never imperatively invoke a subgraph multiple times inside a single node when checkpointing is enabled — use `Send` instead.
- Use `Command(update=..., goto=...)` when you need to update state **and** route in one operation.

---

## 9. Streaming

Always stream in user-facing applications. LangGraph provides two streaming modes:

```python
# Mode 1: stream() — high-level state snapshots per super-step
async for chunk in app.astream({"messages": [msg]}, config=config):
    print(chunk)  # dict of state updates

# Mode 2: astream_events() — granular: every LLM token, tool call, state change
async for event in app.astream_events({"messages": [msg]}, config=config, version="v2"):
    if event["event"] == "on_chat_model_stream":
        token = event["data"]["chunk"].content
        yield token  # stream token to frontend
    elif event["event"] == "on_tool_start":
        yield f"
[Tool: {event['name']}]
"
```

Use `astream_events()` for production UI — it provides the granularity needed for real-time token streaming and tool visibility.

---

## 10. Observability — LangSmith

Set up tracing before writing your first node. Debugging without traces is guesswork.

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=your_key
export LANGCHAIN_PROJECT=my-agent-project
```

That's all — LangSmith automatically instruments every LLM call, tool invocation, and state transition without code changes.

**What to monitor in production:**
- Which node caused latency spikes
- Which tool has the highest failure rate
- Supervisor routing decisions (did it route to the right subagent?)
- Token usage per graph run
- Error frequency per node

**Debugging workflow:**
1. Filter LangSmith by `status:error`
2. Open trace → inspect full input/output at each node
3. Identify failing node → add to regression dataset
4. Run automated evaluations against dataset before each deploy

---

## 11. Graph Compilation Checklist

```python
app = graph.compile(
    checkpointer=checkpointer,         # mandatory for production
    interrupt_before=["human_review"], # pause before sensitive nodes
    interrupt_after=[],                # pause after specific nodes if needed
    recursion_limit=25,                # guard against infinite loops (default 25)
    # store=store,                     # attach long-term memory store
)

# Always validate the graph structure before deploying
app.get_graph().print_ascii()         # visualize in terminal
app.get_graph(xray=True).draw_mermaid_png(output_file_path="graph.png")
```

---

## 12. Testing Strategy

| Test type | What to test | Tool |
|---|---|---|
| **Unit** | Individual node functions in isolation | `pytest` — call node fn directly with mock state |
| **Integration** | Full graph with `InMemorySaver` | `pytest` + `app.invoke()` |
| **Regression** | Known failure cases | LangSmith datasets + automated eval |
| **Load** | Parallelism limits, concurrent threads | LangGraph Cloud / custom stress test |

```python
# Unit test a node — no graph needed
def test_llm_node_calls_tool():
    state = {"messages": [HumanMessage(content="What is the weather in Warsaw?")]}
    result = llm_node(state)
    assert result["messages"][-1].tool_calls  # expect tool call

# Integration test — full graph run
def test_full_agent_flow():
    config = {"configurable": {"thread_id": "test-001"}}
    result = app.invoke({"messages": [HumanMessage(content="Hello")]}, config=config)
    assert result["final_answer"] is not None
```

---

## Quick Reference

```
Graph compile checklist:
  ✅ Persistent checkpointer (PostgresSaver in prod, InMemorySaver in dev)
  ✅ recursion_limit set explicitly
  ✅ LangSmith tracing enabled
  ✅ interrupt_before for all HITL nodes
  ✅ graph.get_graph().print_ascii() — verify topology before deploy

State checklist:
  ✅ Flat TypedDict
  ✅ Reducers on all accumulating fields
  ✅ No large blobs (store references, not data)
  ✅ Error tracking fields present

Node checklist:
  ✅ Single responsibility
  ✅ Returns dict (partial update)
  ✅ Retry policy defined
  ✅ try/except with structured error output

Multi-agent checklist:
  ✅ Supervisor passes explicit task context on handoff
  ✅ Subagents are independently testable
  ✅ Use Send API for parallel fan-out, not imperative loops
  ✅ All agents return to supervisor (or END)
```


## Common commands

All Python commands assume `cd app/` first.

```bash
# Install (uses uv; the Dockerfile pins via uv.lock)
uv sync                                 # full install incl. dev deps
pip install -e . "langgraph-cli[inmem]" # alt for ad-hoc langgraph dev

# Run the API locally (with auto-reload via override compose)
docker compose up                       # postgres + backend on http://localhost:3000
# Backend hot-reloads on edits to app/src/

# Run the production stack (frontend + backend + postgres)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# LangGraph Studio (uses app/langgraph.json)
langgraph dev

# CLI invocation
python src/cli.py "your query" --infosphere polish --report full
python src/cli.py "your query" --report compact --log-level DEBUG

# Tests
make test                               # unit tests (tests/unit_tests/)
make test TEST_FILE=tests/unit_tests/test_api.py
python -m pytest tests/unit_tests/test_api.py::test_name -vv  # single test
make integration_tests                  # tests/integration_tests/ — hits real APIs

# Lint / format (ruff + mypy --strict)
make lint                               # check only
make format                             # apply fixes
make spell_check                        # codespell
```

## Required environment

Set in `.env` at the repo root (loaded by docker compose) or `app/.env` (loaded via `python-dotenv` in `init_environment()`):

- `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY` — required; `require_env()` raises on startup if missing.
- `DATABASE_URL` — optional; without it, prompt logging is silently disabled.
- `CORS_ALLOW_ORIGINS` — comma-separated; defaults to localhost variants.
- `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_OUTPUT_TOKENS`, `ANALYST_ADDITIONAL_SOURCES` — tuning knobs read by `config.py`.
- `API_RATE_LIMIT_REQUESTS`, `API_RATE_LIMIT_WINDOW_SECONDS` — rate-limit overrides.
- `AUTH_USER`, `AUTH_PASSWORD` — only consumed by the prod frontend container's entrypoint to generate `htpasswd` for nginx basic auth.
- `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` — optional tracing.
- `FRONTEND_HTML_PATH` — override only if the frontend bind mount path differs from `/app/frontend/index.html`.

## Things that bite

- **Don't add new top-level Python modules to the repo root.** Imports inside `app/src/` assume `src/` is on `sys.path` (set as `PYTHONPATH=/app/src` in the override compose; `tool.setuptools.package-dir` in `pyproject.toml`).
- **Polish vs English prompts and sources are not interchangeable.** Both the LLM prompts and the curated `INFOSPHERE_SOURCES` switch on the `language`/`infosphere` argument that flows through `build_runtime_config(infosphere=...)` into each node via LangGraph's runtime config. There is no per-request graph rebuild; the module-level `graph` is reused.
- **`compose_final`** depends on referee not having blocked — if you change routing, also update the `_route_after_referee` conditional in `graph.py`.
