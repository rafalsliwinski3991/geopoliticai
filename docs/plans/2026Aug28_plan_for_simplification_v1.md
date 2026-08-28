# Plan: simplification pass (from `docs/brainstorming/2026Aug28_brainstorm_v1.md`)

**Date:** 2026-08-28
**Branch:** `2026Aug28-simplify-repo` (already checked out)
**Strategy:** one branch, ordered commits, mechanical deletions first, streaming rewrite last.

---

## 1. Scope summary

### Deleted

| Thing | Where it lives today |
| --- | --- |
| `cli.py` | `app/src/cli.py` (35 lines) |
| `main.py`, the root CLI shim | `main.py:8`, `from cli import main` |
| `"cli"` in the packaging manifest | `app/pyproject.toml:47` |
| `POST /api/run_pipeline` and `RunPipelineResponse` | `app/src/api.py:107-111`, `:235-253` |
| `BackgroundTasks` import and its deferred `log_output` task | `app/src/api.py:14`, `:252` |
| `_ERROR_STATUS` / `_status_for` | `app/src/api.py:167-179` |
| `_sanitize_output` | `app/src/api.py:113-115` |
| `_parse_allowed_origins`, `_read_positive_int_env` and their four constants | `app/src/api.py:28-64` |
| `_resolve_location`, the `httpx` import, the `location` column | `app/src/database.py:8`, `:25`, `:47-60`, `:67-79` |
| `log_prompt`, `log_output`, the `log_id` plumbing | `app/src/database.py:63-97`, `app/src/api.py:194`, `:213-214`, `:242`, `:251-252` |
| `_chunk_text`, replaced by `BaseMessage.text()` | `app/src/agents/expert/graph.py:47-62` |
| `run_pipeline`, `astream_pipeline`, `PipelineEvent`, `NODE_LABELS`, `seen_nodes` | `app/src/agents/expert/graph.py:15-19`, `:65-98` |
| `astream_events(version="v2")` and its event-name matching | `app/src/agents/expert/graph.py:72-86` |

### Rewritten

- **`graph.py`** becomes construction only: `build_graph`, `build_runtime_config`, the `init_tracing()` call, `graph`. Ends at 31 lines.
- **`api.py`** owns the run loop. `graph.astream(..., stream_mode="messages")`, filtered on `metadata["langgraph_node"] == "answer"` and on `isinstance(message, AIMessage)`, with `BaseMessage.text()` doing the content-block flattening. Progress is inferred: the search label before the run starts, the answer label on the first token.
- **`models.py`** holds one exception hierarchy. `LLMInvocationError` moves in under `PipelineError`; every class carries `status`.
- **`database.py`** writes one row after a successful run and stays silent on failure. Lands at 52 lines.

### Kept deliberately

Every multi-agent seam, on the user's stated plan that more agents arrive soon: the `agents/<name>/` layout, the no-agent-imports rule, `SourcePolicy`, `ANSWER_LLM_SETTINGS`, `RetrievalSettings`, and all three `graph.py` build helpers including `build_runtime_config`'s unreachable `thread_id` branch. Also kept on the user's call: the in-process rate limiter, both defensive pieces in `search.py` (`build_batch_query`'s domain-dropping loop and the `_extract_sync`/`_extract_text` pair), and `init_tracing()` at module scope in `graph.py`.

### Where the code disagrees with the brainstorm

1. **The brainstorm keeps `status` on the error classes so the frontend can distinguish failures, but after the sync endpoint is deleted nothing reads a status.** Pipeline failures now happen after the response headers are committed at 200, so they can only travel inside an SSE frame. `_status_for` is not "collapsed into the classes", it is deleted with its only caller. This plan keeps `status` per the settled decision and gives it a live consumer by adding it to the SSE error frame. See §6, finding D5.
2. **The brainstorm counts four error classes and says `_ERROR_STATUS` is a lookup table used at both catch sites.** Only the sync endpoint uses it (`api.py:247`); the stream endpoint at `api.py:216` catches the union and never maps a status. So this commit deletes less from the stream path than the brainstorm implies.
3. **`main.py` at the repo root executes `from cli import main`.** The brainstorm's round-5 verification ("no Makefile target, Dockerfile entrypoint, compose command, or test references `cli.py`") checked those four places and missed this one. Deleting `cli.py` without deleting `main.py` leaves `python main.py "query"` raising `ModuleNotFoundError` at import. The root `Dockerfile` does `COPY . .` so the broken shim ships in that image, though its `CMD` is `uvicorn` and is unaffected.
4. **The brainstorm does not mention `app/pyproject.toml`'s `py-modules` list, which names `"cli"`.** Deleting `cli.py` without editing it leaves the wheel manifest referencing a missing module. Development is unaffected (the venv install is a `.pth` file pointing at `app/src`), but the Docker build does a real non-editable `uv sync`.
5. **The brainstorm says `api.py` has two env parsers; there is a third env read it does not list**, `FRONTEND_HTML_PATH` at `api.py:145`. It is out of scope and stays.
6. **`_chunk_text` is on the live token path today.** `astream_events` emits `on_chat_model_stream` from the model's callback manager, which does not pass through `astream_text`'s `isinstance(content, str)` filter, so `graph.py:47` runs on every token today. Only its list branch is unreached, because ChatOpenAI returns string content. This plan deletes the helper rather than moving it: `BaseMessage.text()` in langchain-core 0.3.83 does the same flattening and additionally keeps bare-string blocks, which `_chunk_text` silently drops. See §6, finding F2.
7. **`astream_events(version="v2")` is not deprecated in langchain-core 0.3.83.** It carries no deprecation decorator and emits no warning, and `v2` is its default. The rewrite is justified by removing an abstraction layer and event-name string matching, not by the older API being retired. This distinction must not be written into the three guidance files.
8. **The api-level "empty answer" check is already dead and stays dead.** `answer.py:43` raises `LLMInvocationError` when the model produces nothing, so `api.py`'s `if not output` branch cannot fire. It is retained as a cheap guard, not as live behaviour.
9. **`make lint` is already red on this branch, before any change in this plan.** `mypy --strict` reports `src/tracing.py:32: error: Unused "type: ignore" comment`, because `arize-phoenix-otel` is a hard dependency and so `phoenix.otel` always resolves. Commit 8 is the only commit gated on `make lint`, so this pass has to fix it or the gate can never pass. Commit 0 fixes it.

### Verified against the installed environment

Run in `app/.venv`: langgraph 1.0.1, langchain-core 0.3.83, langchain-openai 0.3.35, fastapi 0.135.1, pydantic 2.12.5, httpx 0.28.1, asyncpg 0.31.0, trafilatura 2.2.0, Python 3.12 locally and 3.11 in CI and Docker.

`Pregel.astream` in this version has the signature `(input, config=None, *, context=None, stream_mode=None, print_mode=(), output_keys=None, interrupt_before=None, interrupt_after=None, durability=None, subgraphs=False, debug=None)`. Driving this exact graph with `stream_mode="messages"` and a `FakeListChatModel` yields `(AIMessageChunk, metadata)` two-tuples, one per token, with `metadata["langgraph_node"] == "answer"`, and nothing from `search_and_fetch`. Exceptions raised inside a node propagate out of `astream` unchanged.

---

## 2. Ordered commits

Each commit updates `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` for its own change, per this repo's own rule. `make test` from `app/` must pass before moving on; commits 0 and 8 also run `make lint`.

**Pre-flight, before commit 0.** With `main` checked out and a real `.env`, capture a reference SSE transcript so commit 8 can be diffed against today's behaviour rather than against the plan's description of it:

```bash
cd app && .venv/bin/uvicorn api:app --port 8000 &
curl -N -X POST localhost:8000/api/run_pipeline/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the current state of the Ukraine ceasefire negotiations?"}' \
  > /tmp/sse_before.txt
```

Re-run the identical command after commit 8 and compare the frame sequence and the assembled answer. This is the substitute for keeping a second entrypoint alive to A/B against.

| # | Commit | Risk |
| --- | --- | --- |
| 0 | Fix the pre-existing `mypy --strict` failure | mechanical |
| 1 | Delete the CLI and its root shim | mechanical |
| 2 | Delete the sync endpoint and its error mapping | mechanical |
| 3 | Delete `_sanitize_output` | mechanical |
| 4 | Hardcode the CORS and rate-limit settings | mechanical |
| 5 | Collapse the error classes into one hierarchy | small, wide |
| 6 | Remove the location feature | mechanical + schema |
| 7 | `database.py`: one insert, successes only | small |
| 8 | Move the run loop into `api.py`, `graph.py` becomes construction only | the risky one |

**On test churn.** Section 4 describes the end state of every test. Several tests are touched more than once on the way there, and each commit is responsible for leaving `make test` green with the code as it stands at that commit. The per-commit notes below name every interim edit. Do not write an end-state assertion early; `patch("api._astream_answer", ...)` raises `AttributeError` until commit 8 creates that function, and `events[-1]["status"]` raises `KeyError` until commit 8 adds that key.

### Commit 0 — Fix the pre-existing `mypy --strict` failure

**Files:** `app/src/tracing.py`.

Delete the `# type: ignore[import-not-found]` comment on `tracing.py:32`. `arize-phoenix-otel` is a hard runtime dependency in `app/pyproject.toml`, so `phoenix.otel` always resolves and the ignore is unused under `--strict`. Nothing else changes.

**Safe here because** it touches one comment and no runtime behaviour, and it is the precondition for commit 8's `make lint` gate meaning anything. Kept as its own commit so the fix is not confused with this pass's real changes.

**Test:** `cd app && make test && make lint`

### Commit 1 — Delete the CLI and its root shim

**Files:** delete `app/src/cli.py` and `main.py`; edit `app/pyproject.toml`, `app/README.md`, `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`.

**Safe here because** after `main.py` goes with it, nothing executable references either file. Verified: no Makefile target, no compose `command`, no test, no CI step; `app/Dockerfile`'s `CMD` and the root `Dockerfile`'s `CMD` are both `uvicorn api:app`. `run_pipeline` keeps a consumer (the sync endpoint) until commit 2, so this commit does not orphan anything.

**Tests touched:** none.

**Test:** `cd app && make test`

### Commit 2 — Delete the sync endpoint and its error mapping

**Files:** `app/src/api.py`, `app/tests/unit_tests/test_api.py`, the three guidance files.

**Safe here because** `frontend/index.html:428` calls only `/api/run_pipeline/stream`; the sync route's only in-repo callers are the five unit tests handled in this commit. `_status_for` and `_ERROR_STATUS` have no other caller (`api.py:247` is the sole use), so they leave with it. `run_pipeline` is now unreferenced but stays in `graph.py` until commit 8, keeping this diff to one file of source.

**Also in this commit:** the import block. `BackgroundTasks` (`api.py:14`), `run_pipeline` (`:21`), and `NoSourcesError`/`SearchUnavailableError` (`:24`) all become unused here, not at commit 8. `make test` does not run ruff, so leaving them would hide four `F401`s until the commit-8 lint gate. `PipelineError` and `LLMInvocationError` are still used at `api.py:216`.

**Tests touched (interim state, against `api.astream_pipeline`, no `status` key yet):**

- `test_unknown_legacy_field_is_ignored` → retarget at `/api/run_pipeline/stream`, patching `api.astream_pipeline`.
- `test_sync_maps_pipeline_errors` → delete. Its replacement cannot exist until commit 5 creates the `status` attributes and commit 8 emits them.
- `test_sync_logs_prompt_and_output` → delete.
- `test_query_validation` → retarget at the stream route. Both assertions still expect 422 from pydantic.
- `test_rate_limiting_enforced` → retarget at the stream route, patching `api.astream_pipeline`.
- New `test_sync_route_is_gone` → `POST /api/run_pipeline` returns 404.

**Test:** `cd app && make test`

### Commit 3 — Delete `_sanitize_output`

**Files:** `app/src/api.py`.

**Safe here because** after commit 2 it has one caller, `api.py:215`, and `_sse` cannot hand it anything that needs sanitizing: `json.dumps` defaults to `ensure_ascii=True` and escapes lone surrogates, so the response body encodes cleanly without it. Verified: `json.dumps({"output": "\ud800abc"})` returns `{"output": "\ud800abc"}` and encodes to UTF-8 without error. Note the function is *not* a no-op on its own — the encode/decode round-trip does replace a lone surrogate with U+FFFD — but it never sees one, and today's token frames at `api.py:206` already bypass it, so it has never covered the streaming path.

**Tests touched:** none.

**Test:** `cd app && make test`

### Commit 4 — Hardcode the CORS and rate-limit settings

**Files:** `app/src/api.py`, the three guidance files.

**Safe here because** neither `docker-compose.yml` nor `docker-compose.override.yml` sets `CORS_ALLOW_ORIGINS`, `API_RATE_LIMIT_REQUESTS`, or `API_RATE_LIMIT_WINDOW_SECONDS`, so every deployment in this repo already runs the defaults. This resolves the brainstorm's own objection to "declared settings": the repo rule is hardcoded dataclasses, and `pydantic-settings` is not installed.

**Tests touched:** none.

**Test:** `cd app && make test`

### Commit 5 — Collapse the error classes into one hierarchy

**Files:** `app/src/models.py`, `app/src/llm.py`, `app/src/agents/expert/nodes/answer.py`, `app/src/api.py`, new `app/tests/unit_tests/test_models.py`, the three guidance files.

**Safe here because** `llm.py` re-imports `LLMInvocationError` from `models`, so `from llm import LLMInvocationError` keeps working for `test_api.py`, `test_expert_graph.py`, and `answer.py`. Import direction holds: `models.py` still imports nothing local, and `llm.py` already imports `config`.

**Tests touched:** new `test_models.py` only. `test_api.py`'s `except` behaviour is unchanged from the outside, because `LLMInvocationError` was already caught by the union it replaces.

**Test:** `cd app && make test`

### Commit 6 — Remove the location feature

**Files:** `app/src/database.py`, `app/tests/unit_tests/test_database.py`, the three guidance files.

**Safe here because** `location` appears only in `database.py` (schema, resolver, insert) and `test_database.py` (three patch sites). The matches in `search.py:160-164` and `test_fetch.py` are the HTTP `Location` redirect header.

**Tests touched — three sites, not one.** `unittest.mock.patch` raises `AttributeError` when its target does not exist, so every reference must go in the same commit:

- `test_log_prompt_returns_row_id_on_success` (`test_database.py:23`) → drop the `patch("database._resolve_location", ...)` wrapper, keep the rest.
- `test_log_prompt_handles_exception_gracefully` (`test_database.py:49`) → same.
- `test_log_prompt_resolves_location` (`test_database.py:121`) → delete.

**Test:** `cd app && make test`

### Commit 7 — `database.py`: one insert, successes only

**Files:** `app/src/database.py`, `app/src/api.py`, `app/tests/unit_tests/test_database.py`, `app/tests/unit_tests/test_api.py`, the three guidance files.

**Safe here because** after commit 2 there is exactly one call site for each of `log_prompt` and `log_output`, both inside the stream endpoint, and both collapse into a single `log_run` call in the same function. Nothing outside `api.py` imports `database`.

**Tests touched:** `test_database.py` collapses to its final four tests; `test_stream_logs_output_before_result` and `test_stream_progress_tokens_result` in `test_api.py` swap `log_prompt`/`log_output` for `log_run` while still patching `api.astream_pipeline`.

**Test:** `cd app && make test`

### Commit 8 — Move the run loop into `api.py`

**Files:** `app/src/agents/expert/graph.py`, `app/src/agents/expert/__init__.py`, `app/src/api.py`, `app/tests/unit_tests/test_api.py`, `app/tests/integration_tests/test_expert_graph.py`, the three guidance files.

**Safe here because** every other consumer of `graph.py`'s orchestration is already gone: the CLI in commit 1, the sync endpoint in commit 2. The stream endpoint is the only caller left, and it is rewritten in the same diff. `langgraph.json` points at `./src/agents/expert/graph.py:graph`, and `graph` survives at module scope with `init_tracing()` still above it.

**Tests touched:** every `api.astream_pipeline` patch target becomes `api._astream_answer` and its stub becomes a plain `AsyncIterator[str]`; `test_stream_reports_error_status_per_type` is added; the integration tests are rewritten. Section 4 has the details.

**Test:** `cd app && make test && make integration_tests && make lint`, then re-run the pre-flight `curl` and diff against `/tmp/sse_before.txt`.

## 3. Concrete before/after code

### 3.0 `main.py` (commit 1)

Deleted in full:

```python
"""Backward-compatible entrypoint for the GeopoliticAI CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app" / "src"))

from cli import main  # noqa: E402

if __name__ == "__main__":
    main()
```

Nothing replaces it. The root `Dockerfile` copies the whole tree but runs `uvicorn api:app`, so removing this file does not change that image's behaviour.

### 3.0b `app/src/tracing.py` (commit 0)

Before (`tracing.py:32`):

```python
        from phoenix.otel import register  # type: ignore[import-not-found]
```

After:

```python
        from phoenix.otel import register
```

### 3.1 `app/pyproject.toml` (commit 1)

Before:

```toml
py-modules = [
    "api",
    "cli",
    "config",
    "database",
    "llm",
    "models",
    "search",
    "tracing",
]
```

After:

```toml
py-modules = [
    "api",
    "config",
    "database",
    "llm",
    "models",
    "search",
    "tracing",
]
```

### 3.2 `app/src/api.py` imports and module constants (commits 2, 4, 5, 8)

Before (`api.py:1-64`):

```python
"""FastAPI application for the GeopoliticAI expert agent."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import database
from agents.expert import NODE_LABELS, astream_pipeline, run_pipeline
from config import init_environment, require_env
from llm import LLMInvocationError
from models import NoSourcesError, PipelineError, SearchUnavailableError
from tracing import init_tracing

logger = logging.getLogger(__name__)
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5173",
)
MAX_QUERY_LENGTH = 2_000
DEFAULT_RATE_LIMIT_REQUESTS = 20
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_store: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()


def _parse_allowed_origins() -> list[str]:
    """Parse CORS origins from the environment."""
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def _read_positive_int_env(var_name: str, default: int) -> int:
    """Read a positive integer setting, falling back for malformed values."""
    raw = os.getenv(var_name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


RATE_LIMIT_REQUESTS = _read_positive_int_env(
    "API_RATE_LIMIT_REQUESTS", DEFAULT_RATE_LIMIT_REQUESTS
)
RATE_LIMIT_WINDOW_SECONDS = _read_positive_int_env(
    "API_RATE_LIMIT_WINDOW_SECONDS", DEFAULT_RATE_LIMIT_WINDOW_SECONDS
)
```

After:

```python
"""FastAPI application for the GeopoliticAI expert agent."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, AsyncGenerator

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, field_validator

import database
from agents.expert import build_initial_pipeline_state, build_runtime_config, graph
from config import init_environment, require_env
from models import PipelineError
from tracing import init_tracing

logger = logging.getLogger(__name__)

# Hardcoded the way `LLMSettings` is hardcoded: edited here, never read from
# the environment. Nothing in compose overrides these today.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5173",
]
MAX_QUERY_LENGTH = 2_000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60

SEARCH_PROGRESS = {
    "node": "search_and_fetch",
    "label": "Searching and reading sources...",
}
ANSWER_PROGRESS = {"node": "answer", "label": "Writing the answer..."}

_rate_limit_store: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()
```

`os` stays imported: `lifespan` reads `DATABASE_URL` and the frontend path constants at `api.py:145-146` still use it.

The middleware registration loses its function call:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

### 3.3 `app/src/api.py` — the deleted sync half (commit 2)

Deleted verbatim, `api.py:107-111` and `:167-179` and `:235-253`:

```python
class RunPipelineResponse(BaseModel):
    """Response payload containing the final answer."""

    output: str


_ERROR_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (NoSourcesError, 422),
    (SearchUnavailableError, 503),
    (LLMInvocationError, 502),
)


def _status_for(exc: Exception) -> int:
    """Map a known pipeline failure to its HTTP status code."""
    for error_type, status in _ERROR_STATUS:
        if isinstance(exc, error_type):
            return status
    return 500


@router.post("/run_pipeline", response_model=RunPipelineResponse)
async def run_pipeline_endpoint(
    payload: RunPipelineRequest, request: Request, background_tasks: BackgroundTasks
) -> RunPipelineResponse:
    """Run the pipeline and return its final output."""
    _enforce_rate_limit(request)
    client_id = _resolve_client_id(request)
    log_id = await database.log_prompt(payload.query, client_id)
    try:
        output = await run_pipeline(payload.query)
    except (PipelineError, LLMInvocationError) as exc:
        logger.warning("Pipeline failed: %s", exc)
        raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from None
    except Exception:
        logger.exception("Pipeline failed unexpectedly.")
        raise HTTPException(status_code=500, detail="Internal server error.") from None
    if log_id is not None:
        background_tasks.add_task(database.log_output, log_id, output)
    return RunPipelineResponse(output=_sanitize_output(output))
```

Nothing replaces it. `HTTPException` stays imported for `serve_frontend` (`api.py:158`) and `_enforce_rate_limit` (`api.py:138`).

### 3.4 `app/src/models.py` (commit 5)

Before (`models.py:1-17`):

```python
"""Shared data structures for every agent in this repository."""

from __future__ import annotations

from dataclasses import dataclass


class PipelineError(RuntimeError):
    """A failure the client must see, never a degraded answer."""


class SearchUnavailableError(PipelineError):
    """Every Brave request attempted for this run failed."""


class NoSourcesError(PipelineError):
    """No allow-listed page survived search, fetch, and extraction."""
```

After:

```python
"""Shared data structures for every agent in this repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


class PipelineError(RuntimeError):
    """A failure the client must see, never a degraded answer.

    `status` is the HTTP code a delivery layer reports for this failure.
    It lives on the class so adding an error type cannot leave a lookup
    table behind.
    """

    status: ClassVar[int] = 500


class SearchUnavailableError(PipelineError):
    """Every Brave request attempted for this run failed."""

    status: ClassVar[int] = 503


class NoSourcesError(PipelineError):
    """No allow-listed page survived search, fetch, and extraction."""

    status: ClassVar[int] = 422


class LLMInvocationError(PipelineError):
    """The model call failed or returned nothing usable."""

    status: ClassVar[int] = 502
```

The `Candidate`, `Source`, and `SourcePolicy` dataclasses below are untouched.

### 3.5 `app/src/llm.py` (commit 5)

Before (`llm.py:1-17`):

```python
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from config import DEFAULT_LLM_SETTINGS, LLMSettings

DEFAULT_MAX_RETRIES = 2


class LLMInvocationError(RuntimeError):
    """Raised when the model call fails or returns nothing usable."""
```

After:

```python
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from config import DEFAULT_LLM_SETTINGS, LLMSettings
from models import LLMInvocationError

DEFAULT_MAX_RETRIES = 2
```

`astream_text`'s `raise LLMInvocationError("Model call failed.") from exc` at `llm.py:47` is unchanged, so the name is used and ruff's F401 does not fire. `from llm import LLMInvocationError` keeps resolving, which is what `test_api.py:9` and `answer.py:11` rely on today.

### 3.6 `app/src/agents/expert/nodes/answer.py` (commit 5)

Before (`answer.py:11-12`):

```python
from llm import LLMInvocationError, astream_text
from models import NoSourcesError, Source
```

After:

```python
from llm import astream_text
from models import LLMInvocationError, NoSourcesError, Source
```

Both raise sites in the node body are unchanged.

### 3.7 `app/src/database.py` (commits 6 and 7)

Before, the whole file after `close_pool` (`database.py:47-97`):

```python
async def _resolve_location(ip: str) -> str:
    if ip in ("unknown", "127.0.0.1", "::1"):
        return "local"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "city,country"},
            )
            data = resp.json()
        parts = [data.get("city", ""), data.get("country", "")]
        return ", ".join(p for p in parts if p) or "unknown"
    except Exception:
        return "unknown"


async def log_prompt(prompt: str, ip: str) -> int | None:
    """Insert a prompt log row and return its ID; returns None if DB unavailable."""
    if _pool is None:
        return None
    location = await _resolve_location(ip)
    try:
        async with _pool.acquire() as conn:
            row_id = await conn.fetchval(
                """
                INSERT INTO prompt_logs (prompt, ip, location)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                prompt,
                ip,
                location,
            )
            return cast(int, row_id)
    except Exception:
        return None


async def log_output(log_id: int, output: str) -> None:
    """Update a prompt log row with the pipeline output."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE prompt_logs SET output = $1 WHERE id = $2",
                output,
                log_id,
            )
    except Exception:
        pass
```

After, the whole file:

```python
"""Database module for prompt logging."""

from __future__ import annotations

from typing import Any

import asyncpg  # type: ignore[import-untyped]

_pool: Any | None = None


async def init_pool(dsn: str) -> None:
    """Initialize the asyncpg connection pool and ensure the table exists."""
    global _pool
    _pool = await asyncpg.create_pool(dsn)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_logs (
                id        SERIAL PRIMARY KEY,
                datetime  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                prompt    TEXT        NOT NULL,
                ip        VARCHAR(45),
                output    TEXT
            )
            """
        )
        # Existing deployments predate the output column and carry a location
        # column the app no longer writes.
        await conn.execute(
            "ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS output TEXT"
        )
        await conn.execute("ALTER TABLE prompt_logs DROP COLUMN IF EXISTS location")


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def log_run(prompt: str, ip: str, output: str) -> None:
    """Record one completed run; silent when the database is unavailable."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prompt_logs (prompt, ip, output)
                VALUES ($1, $2, $3)
                """,
                prompt,
                ip,
                output,
            )
    except Exception:
        pass
```

The `cast` and `httpx` imports go with the functions that used them.

### 3.8 `app/src/agents/expert/graph.py` (commit 8)

Before: 98 lines, listed in full in §1. After, the whole file:

```python
"""Graph construction for the expert agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.expert.nodes import answer, search_and_fetch
from agents.expert.state import PipelineState
from tracing import init_tracing


def build_graph() -> Any:
    """Construct and compile the two-node LangGraph pipeline."""
    pipeline = StateGraph(PipelineState)
    pipeline.add_node("search_and_fetch", search_and_fetch)
    pipeline.add_node("answer", answer)
    pipeline.add_edge(START, "search_and_fetch")
    pipeline.add_edge("search_and_fetch", "answer")
    pipeline.add_edge("answer", END)
    return pipeline.compile(name="expert")


def build_runtime_config(*, thread_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Build runtime configuration shared by entrypoints."""
    configurable: dict[str, Any] = {}
    if thread_id is not None:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty when provided.")
        configurable["thread_id"] = thread_id
    return {"configurable": configurable}


# `langgraph dev` imports this module and nothing else, so module scope is
# Studio's only hook for Phoenix tracing. `init_tracing()` is idempotent and
# never raises, so this is not orchestration leaking back into construction.
init_tracing()
graph = build_graph()
```

The `LLMInvocationError` and `AsyncIterator`/`Literal` imports go with the functions that used them.

### 3.9 `app/src/agents/expert/__init__.py` (commit 8)

Before:

```python
"""The expert agent: allow-listed geopolitical research."""

from agents.expert.graph import (
    NODE_LABELS,
    astream_pipeline,
    build_graph,
    graph,
    run_pipeline,
)

__all__ = ["NODE_LABELS", "astream_pipeline", "build_graph", "graph", "run_pipeline"]
```

After:

```python
"""The expert agent: allow-listed geopolitical research."""

from agents.expert.graph import build_graph, build_runtime_config, graph
from agents.expert.state import build_initial_pipeline_state

__all__ = [
    "build_graph",
    "build_initial_pipeline_state",
    "build_runtime_config",
    "graph",
]
```

This is the public interface `api.py` consumes; both sides are shown here and in §3.10.

### 3.10 `app/src/api.py` — the run loop and the stream endpoint (commits 7 and 8)

Before (`api.py:182-232`):

```python
def _sse(payload: dict[str, str]) -> str:
    """Serialize one SSE data frame."""
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/run_pipeline/stream")
async def run_pipeline_stream_endpoint(
    payload: RunPipelineRequest, request: Request
) -> StreamingResponse:
    """Run the pipeline and stream progress and answer tokens over SSE."""
    _enforce_rate_limit(request)
    client_id = _resolve_client_id(request)
    log_id = await database.log_prompt(payload.query, client_id)

    async def _generate() -> AsyncGenerator[str, None]:
        parts: list[str] = []
        try:
            async for kind, value in astream_pipeline(payload.query):
                if kind == "progress":
                    yield _sse(
                        {"type": "progress", "node": value, "label": NODE_LABELS[value]}
                    )
                else:
                    parts.append(value)
                    yield _sse({"type": "token", "content": value})
            output = "".join(parts).strip()
            if not output:
                yield _sse(
                    {"type": "error", "message": "The model returned an empty answer."}
                )
                return
            if log_id is not None:
                await database.log_output(log_id, output)
            yield _sse({"type": "result", "output": _sanitize_output(output)})
        except (PipelineError, LLMInvocationError) as exc:
            logger.warning("Streaming pipeline failed: %s", exc)
            yield _sse({"type": "error", "message": str(exc)})
        except Exception:
            logger.exception("Streaming pipeline failed unexpectedly.")
            yield _sse(
                {
                    "type": "error",
                    "message": "An unexpected error occurred. Please try again.",
                }
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

After:

```python
def _sse(payload: dict[str, Any]) -> str:
    """Serialize one SSE data frame."""
    return f"data: {json.dumps(payload)}\n\n"


async def _astream_answer(query: str) -> AsyncGenerator[str, None]:
    """Run the expert graph, yielding answer text as the model produces it."""
    state = build_initial_pipeline_state(query)
    config = build_runtime_config()
    # `stream_mode="messages"` yields (message, metadata) two-tuples. Do not
    # switch this to the list form (["updates", "messages"]) without changing
    # the unpacking: that form yields (mode, payload) instead, which unpacks
    # without error and then silently matches nothing.
    async for message, metadata in graph.astream(
        state, config=config, stream_mode="messages"
    ):
        # Every LLM call in every node streams through here. Only the answer
        # node's tokens are the user's answer.
        if metadata.get("langgraph_node") != "answer":
            continue
        if not isinstance(message, AIMessage):
            continue
        text = message.text()
        if text:
            yield text


@router.post("/run_pipeline/stream")
async def run_pipeline_stream_endpoint(
    payload: RunPipelineRequest, request: Request
) -> StreamingResponse:
    """Run the pipeline and stream progress and answer tokens over SSE."""
    _enforce_rate_limit(request)
    client_id = _resolve_client_id(request)

    async def _generate() -> AsyncGenerator[str, None]:
        parts: list[str] = []
        try:
            yield _sse({"type": "progress", **SEARCH_PROGRESS})
            async for text in _astream_answer(payload.query):
                if not parts:
                    yield _sse({"type": "progress", **ANSWER_PROGRESS})
                parts.append(text)
                yield _sse({"type": "token", "content": text})
            output = "".join(parts).strip()
            if not output:
                yield _sse(
                    {
                        "type": "error",
                        "status": 502,
                        "message": "The model returned an empty answer.",
                    }
                )
                return
            await database.log_run(payload.query, client_id, output)
            yield _sse({"type": "result", "output": output})
        except PipelineError as exc:
            logger.warning("Streaming pipeline failed: %s", exc)
            yield _sse({"type": "error", "status": exc.status, "message": str(exc)})
        except Exception:
            logger.exception("Streaming pipeline failed unexpectedly.")
            yield _sse(
                {
                    "type": "error",
                    "status": 500,
                    "message": "An unexpected error occurred. Please try again.",
                }
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`_chunk_text` is deleted rather than moved. `BaseMessage.text()` in langchain-core 0.3.83 flattens `{"type": "text", "text": ...}` blocks exactly as `_chunk_text` did, and additionally keeps bare-string blocks, which `content: list[str | dict]` permits and `_chunk_text` silently dropped. `AIMessageChunk` subclasses `AIMessage`, so the single-class `isinstance` covers both.

Five behavioural differences from today, all intended:

1. The `search_and_fetch` progress frame is emitted before the graph starts rather than at node start. It reaches the browser sooner and no longer depends on LangGraph event names. It is also emitted on runs that fail during search, so a failing run now produces two frames, `progress` then `error`, not one.
2. The `answer` progress frame is emitted on the first token rather than at node start. In today's code the gap between the two is the whole search-and-fetch phase; after the change it is the model's time to first token.
3. The `answer` progress frame no longer fires at all when the model produces zero tokens. Today `on_chain_start` fired it regardless. The run ends in an error frame either way, so the browser's progress log is the only thing affected.
4. Error frames gain a `status` key carrying the exception class's own code. The frontend at `frontend/index.html:466` reads only `data.type` and `data.message`, so it ignores the new key; the key exists so the SSE stream stays self-describing without parsing prose, and so the `status` attributes added in commit 5 have a live consumer rather than only a test.
5. Tokens are filtered by `metadata["langgraph_node"]`, preserving the guard `graph.py:83` has today. Redundant for the current two-node graph, and the thing that stops a future second LLM-calling node from streaming its working notes into the user's answer.

### 3.11 `frontend/index.html`

No change. Verified: the SSE reader handles `progress`, `token`, `result`, and `error`, keys `label`, `content`, `output`, `message`. Every one of those still ships. Nothing in the file references `/api/run_pipeline` without the `/stream` suffix.

---

## 4. Test plan

`make test` runs 47 unit tests today and passes. `make lint` does not (see commit 0). Every commit must leave `make test` green with the code as it stands at that commit; §2's per-commit notes carry the interim edits, and this section describes only where each test lands.

### Dies

| Test | File | Killed in | Why |
| --- | --- | --- | --- |
| `test_sync_maps_pipeline_errors` | `test_api.py:56` | 2 | sync endpoint deleted; its successor needs commits 5 and 8 |
| `test_sync_logs_prompt_and_output` | `test_api.py:142` | 2 | sync endpoint deleted, superseded by the stream logging test |
| `test_log_prompt_resolves_location` | `test_database.py:121` | 6 | location feature deleted |
| `test_log_output_returns_none_when_pool_unavailable` | `test_database.py:68` | 7 | `log_output` deleted |
| `test_log_output_updates_row_on_success` | `test_database.py:75` | 7 | `log_output` deleted |
| `test_log_output_handles_exception_gracefully` | `test_database.py:102` | 7 | `log_output` deleted |

Two further tests survive but must be edited in commit 6, because `unittest.mock.patch` raises `AttributeError` on a missing target: `test_log_prompt_returns_row_id_on_success` (`test_database.py:23`) and `test_log_prompt_handles_exception_gracefully` (`test_database.py:49`) both wrap themselves in `patch("database._resolve_location", ...)`. Drop the wrapper, keep the body. They then die in commit 7 with `log_prompt` itself.

### Rewritten

**`test_api.py`**, end state:

- `test_unknown_legacy_field_is_ignored` — posts to `/api/run_pipeline/stream` with the extra field, patching `api._astream_answer`, and asserts a 200 plus a `result` frame.
- `test_stream_progress_tokens_result` — stub is now a plain `AsyncIterator[str]`. Asserts the frame sequence is `progress, progress, token, token, result`, that the first progress label is `"Searching and reading sources..."` and the second is `"Writing the answer..."`, and that the result output is `"Hello world."`.
- `test_stream_logs_output_before_result` — asserts `database.log_run` is awaited exactly once with `("x", "127.0.0.1", "answer")`, and that the await happens before the `result` frame, using the same ordering-list technique as today.
- `test_stream_error_has_no_result` — asserts the frame sequence is `["progress", "error"]`, not a lone error frame. The search progress frame is emitted before the graph is entered, so it survives a failure during search.
- `test_query_validation`, `test_rate_limiting_enforced` — both against `/api/run_pipeline/stream`. The rate-limit test still expects 429 on the twenty-first request, because `_enforce_rate_limit` runs before `StreamingResponse` is constructed and so can still raise an `HTTPException`.

**`test_database.py`** collapses to four tests, all against `log_run`: silent when `_pool is None`; issues an `INSERT INTO prompt_logs` carrying prompt, ip, and output as the three bound parameters; swallows a raising connection; and, new, `init_pool` issues an `ALTER TABLE prompt_logs DROP COLUMN IF EXISTS location`.

**`test_expert_graph.py`** (integration)

- `test_graph_has_exactly_two_nodes` loses its `expert.NODE_LABELS` assertion; the node-set assertion stays.
- `test_graph_is_linear` unchanged.
- `test_execution_emits_progress_and_tokens` → `test_execution_streams_answer_tokens`. Drives `build_graph().astream(state, stream_mode="messages")` directly and asserts the concatenated chunk text is `"Hello world."`. Progress is no longer a graph concern, so that half of the assertion moves to `test_api.py`.
- `test_execution_propagates_llm_failure_after_partial_tokens` → same rewrite, asserting `LLMInvocationError` escapes `astream` after at least one chunk with content `"partial"` has arrived. Verified against langgraph 1.0.1: already-produced chunks are yielded before the exception surfaces, so no partial output is lost.

Both keep their existing `monkeypatch.setattr` on the `search_and_fetch` module globals. Note for whoever writes them: `agents.expert.nodes` re-exports the node functions, which shadows the submodule names, so the patch target must be obtained through `importlib.import_module("agents.expert.nodes.search_and_fetch")` as the current file already does. The same shadowing applies to `agents.expert.graph`, where the package `__init__` binds `graph` to the compiled graph object.

### New

- **`app/tests/unit_tests/test_models.py`** (commit 5) — asserts `LLMInvocationError` is a subclass of `PipelineError`, and that `PipelineError.status`, `NoSourcesError.status`, `SearchUnavailableError.status`, and `LLMInvocationError.status` are 500, 422, 503, and 502.
- **`test_api.py::test_sync_route_is_gone`** (commit 2) — `POST /api/run_pipeline` returns 404.
- **`test_api.py::test_stream_reports_error_status_per_type`** (commit 8) — parametrized over `(NoSourcesError, 422)`, `(SearchUnavailableError, 503)`, `(LLMInvocationError, 502)`. Asserts the frames are `["progress", "error"]`, that the error frame's `status` matches, and that its `message` is `str(error)`. This is what keeps the `status` attributes from rotting.
- **`test_api.py::test_astream_answer_yields_only_answer_node_text`** (commit 8) — the one test that actually executes `_astream_answer`. Every other `test_api.py` test patches it out, which would otherwise leave the pass's only new function untested. It monkeypatches `search_allowlisted` and `fetch_sources` on the `search_and_fetch` module and `llm._build_client` to a `FakeListChatModel`, rebuilds `api.graph`, and asserts the joined output is the model's text. This covers the node filter, the `isinstance` narrowing, and `message.text()` together.
- **`test_database.py::test_init_pool_drops_location_column`** (commit 6) — patches `asyncpg.create_pool` and asserts the `DROP COLUMN IF EXISTS location` statement is issued. It must reset `database._pool = None` afterwards, or through a fixture: `init_pool` writes the module global, and every later test that does not set it explicitly would otherwise see a `MagicMock` pool.

### Unchanged

`test_search.py`, `test_fetch.py`, `test_sources.py`, `test_answer.py`, `test_search_and_fetch.py`, `test_config_env.py`, `test_tracing.py`, `test_frontend_security.py`, `conftest.py`. `test_answer.py` imports `NoSourcesError` from `models` and never names `LLMInvocationError`, so commit 5 does not touch it.

---

## 5. Migration and rollout notes

**Schema.** `init_pool` gains `ALTER TABLE prompt_logs DROP COLUMN IF EXISTS location`. This is destructive and irreversible for whatever the column holds, and it runs on the next backend start against the existing `postgres_data` volume. Dump the table first if those values matter:

```bash
docker compose exec postgres pg_dump -U geopoliticai -t prompt_logs geopoliticai > prompt_logs_backup.sql
```

**Rollback is not symmetric, and this is the sharpest edge in the pass.** Reverting the branch after deploying does not merely lose the column's data. The reverted `CREATE TABLE IF NOT EXISTS` finds the table already present, so the column does not come back, and the reverted `log_prompt` then issues `INSERT INTO prompt_logs (prompt, ip, location)` against a table with no such column. asyncpg raises `UndefinedColumnError`, and `database.py:81`'s bare `except Exception: return None` swallows it. The rolled-back deployment serves answers correctly and logs nothing, permanently, with no error line anywhere. Rolling back therefore requires re-adding the column by hand:

```sql
ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS location VARCHAR(255);
```

**The DDL runs on every backend start**, not only the first, taking `ACCESS EXCLUSIVE` on `prompt_logs` each boot. Harmless at one replica against a small table; it serializes behind in-flight inserts if this ever runs more than one backend. A one-time migration would be the safer shape and is the scouted escape hatch.

**Data shape change.** Rows are now written once, after a successful run, so `output` is never null on a new row and a failed run leaves no row at all. Any query that counts attempts by counting rows will silently start counting successes. Existing rows keep their old shape minus `location`.

**Config.** `CORS_ALLOW_ORIGINS`, `API_RATE_LIMIT_REQUESTS`, and `API_RATE_LIMIT_WINDOW_SECONDS` stop being read. Nothing in this repo sets them, but they must be removed from any deployment env file outside it or they become silently inert. No new environment variable is introduced and no new dependency is added.

**Interface removals.** `POST /api/run_pipeline` disappears; any caller outside this repo breaks with a 404. `python src/cli.py` and `python main.py` both disappear. After this pass the only ways to run the pipeline are the SSE endpoint and `langgraph dev` with Studio, so ad-hoc debugging means a browser, Studio, or `curl -N`.

**Packaging.** `app/pyproject.toml`'s `py-modules` drops `"cli"`. The local venv is an editable `.pth` pointing at `app/src` and is unaffected, but `docker build ./app` performs a real `uv sync --frozen --no-dev` and must not reference a missing module. `uv.lock` needs no change: no dependency is added or removed.

**Documentation this repo's own rule requires updating**, per `CLAUDE.md:3`:

- `AGENTS.md` — line 14 (delivery modules list), 19 (`api.py` and `cli.py` name `agents.expert`), 48 (the three `init_tracing` call sites), 71-72 (route list), 74 (the 422/503/502 sentence, which must now say the codes travel in the SSE error frame), 88 (CLI command).
- `CLAUDE.md` — line 10 (API/CLI/database delivery), 28 (sync and SSE endpoints), 33-34 (the CLI command), 48 (tracing call sites).
- `.github/copilot-instructions.md` — lines 15, 26, 44 (sync/SSE routes), 48, 53.
- `app/README.md` — lines 33-38, the CLI block.

Do not write "astream_events is deprecated" into any of them. It is not deprecated in langchain-core 0.3.83; the reason for the rewrite is one fewer abstraction layer and no event-name string matching.

`README.md` at the repo root describes a seven-agent design that does not exist and is untouched by this pass.

**Rollout.** Deploy is a normal `docker compose up --build`. There is no flag and no staged rollout; the schema change and the route removal land together.

---

## 6. Open questions and rejected objections

Three reviewers read the source rather than this plan. Findings are labelled C (correctness), F (framework), D (devil's advocate). Every finding is recorded with its disposition.

### Accepted, plan changed

| # | Finding | Change made |
| --- | --- | --- |
| C1, F1 | `main.py:8` executes `from cli import main`; commit 1's "nothing executable references it" was false. | `main.py` deleted in commit 1; §3.0 shows the file; §1 records the disagreement; §5 names both entrypoints. |
| C2, D1 | The test rewrites were written for the end state only, so commits 2 through 7 would leave `make test` red (`patch("api._astream_answer")` raises `AttributeError`; `events[-1]["status"]` raises `KeyError`). | §2 now carries per-commit test notes naming every interim edit; §4 states the rule explicitly. |
| C3 | A failing run emits `["progress", "error"]`, not a lone error frame, because the search progress frame precedes the graph. | §4's assertions corrected; §3.10 lists it as intended difference 1. |
| C4 | `make lint` is already red: `tracing.py:32` has an unused `type: ignore` under `mypy --strict`. Commit 8 is the only lint-gated commit. | New commit 0; §3.0b shows the one-line fix. |
| C5 | Two `ruff format --diff` failures in the after-code as written. | Both snippets reformatted to ruff's exact output, verified by running `ruff format`. |
| C6, D1 | `test_database.py:23` and `:49` also patch `_resolve_location`; the Dies table listed only `:121`. | §2 commit 6 and §4 now name all three sites and the `AttributeError` mechanism. |
| C7 | `BackgroundTasks`, `run_pipeline`, `NoSourcesError`, `SearchUnavailableError` become unused at commit 2, not commit 8; `make test` does not run ruff so four F401s would hide until the lint gate. | §2 commit 2 now owns the import block. |
| C8 | `_chunk_text` *is* on the live token path today; §1's claim that it never runs was wrong. | §1 item 6 rewritten with the real mechanism. |
| C9, F3, D4 | `_astream_answer` discarded the metadata, dropping the `langgraph_node == "answer"` guard that `graph.py:83` has today. Silent corruption the first time a second LLM-calling node exists. | Filter restored in §3.10, with a comment. Removing a seam while keeping every adjacent seam for the same stated reason was incoherent. |
| C10a | The `answer` progress frame never fires at all on a zero-token run; the plan listed only the timing change. | §3.10 difference 3. |
| C10b | `test_init_pool_drops_location_column` writes `database._pool` with no reset, poisoning later tests. | §4 requires the reset. |
| F2 | `BaseMessage.text()` in langchain-core 0.3.83 does everything `_chunk_text` does and also keeps bare-string blocks, which `content: list[str \| dict]` permits and `_chunk_text` drops. | `_chunk_text` deleted, `message.text()` used. Verified: for `[{"type":"text","text":"a"}, "b", {"type":"image_url",...}]`, `.text()` returns `"ab"` and `_chunk_text` returns `"a"`. **This overrides a settled brainstorm decision** ("`_chunk_text` is KEPT, the template has the same helper"). The decision's stated purpose was handling content blocks; `.text()` handles them strictly better, and the original argument was from a template rather than from this repo. Flagged for veto. |
| F4 | Whoever later adopts `stream_mode=["updates","messages"]` gets `(mode, payload)` tuples that unpack without error and then match nothing, producing "empty answer" instead of an exception. | Comment added at the `astream` call site. |
| F5 | "astream_events is superseded" is false for langchain-core 0.3.83: no deprecation decorator, no warning, `v2` is the default. | §1 item 7; §5 forbids writing it into the guidance files. |
| D9 | `_sanitize_output` is not a no-op, it does replace lone surrogates; the deletion is safe for a different reason. | §2 commit 3's rationale rewritten: `json.dumps` with `ensure_ascii=True` escapes surrogates before the encoder sees them, and token frames already bypassed the guard. |
| D10 | Doing the streaming rewrite last means that by the time you write it, every way to compare against old behaviour is gone. | Accepted in substance, rejected in form. Reordering would mean writing the new loop while `run_pipeline` and the sync endpoint still stand, i.e. three streaming implementations live at once. Instead §2 adds a pre-flight step: capture a real SSE transcript on `main` and diff it after commit 8. |
| F6b | The `ALTER TABLE` runs on every boot, taking `ACCESS EXCLUSIVE` each time. | §5 records it and names the one-time-migration escape hatch. |

### Accepted as analysis, decision held

| # | Finding | Why held |
| --- | --- | --- |
| D2, F6a | Dropping the `location` column makes rollback silently disable all logging: the reverted `log_prompt` inserts into a column that no longer exists and the bare `except` swallows the error. Leaving a nullable column nobody writes costs one catalog entry. | This is the strongest argument in the three reviews for reversing a settled decision, and it is correct. The brainstorm's round 16 put exactly this question (option 4, drop the column) and the user chose it over leaving it. §5 now documents the trap and the manual `ADD COLUMN` needed to recover. **Recommended for reconsideration before commit 6 lands** — it is the only irreversible step in the pass, and dropping it costs nothing else. |
| D6 | Observability goes to zero. Rows disappear for failed runs, for runs abandoned at the frontend's 10-minute abort or nginx's `proxy_read_timeout 600s`, and for every run if the DB is misconfigured, because `log_run` keeps a bare `except: pass` and the module has no logger. Every outcome is now HTTP 200. One line in the `except PipelineError` branch would preserve the `NoSourcesError` rows, which name the queries the allow-list cannot serve. | Settled twice: round 9 chose successes-only and round 16 chose no logger, both held under challenge. Recorded, not changed. The one-line mitigation stays available. |
| D7 | After commit 8 nothing reads `state["answer"]`. The answer node still accumulates, joins, and strips, and `api.py` independently accumulates, joins, and strips the same tokens, so "streaming is done twice" is only reduced from three copies to two. A CLI calling `graph.ainvoke` is what would keep that key honest. | True. It is a direct consequence of deleting the CLI, which round 5 settled and held. The third state key stays write-only, read only by LangGraph Studio. |
| D8 | Retained items contradict the stated goal: `build_runtime_config` always returns `{"configurable": {}}` and is exported through two modules to compute a constant; `ANSWER_LLM_SETTINGS` is a field-for-field copy of the defaults with no test comparing them; `build_batch_query`'s loop is unreachable; the `_extract_sync`/`_extract_text` pair has no recorded argument in its favour. | All four are explicit user decisions from rounds 12 to 14, each held after challenge. Carried as flags in the brainstorm and unchanged here. The offered mitigations (a comment marking `ANSWER_LLM_SETTINGS` a deliberate copy, a test asserting every batch fits the Brave budget) remain available and unadopted. |

### Rejected

| # | Finding | Why |
| --- | --- | --- |
| D5 | The `status` work is ceremony replacing ceremony: `_status_for` returns 500 for an unmapped class and a subclass that forgets `status` inherits 500, so both fail identically and silently, and `test_models.py` is the lookup table relocated to the test directory. | Half accepted, half rejected. The `ClassVar` is the settled decision from round 2 and stays. The SSE `status` key was this plan's own addition, and dropping it would leave `status` with no consumer outside a test, which is the criticism's own strongest form. Keeping both gives the attribute a live reader for one key the frontend already ignores. Either half can be dropped on the user's word. |
| D-cheap-1 | Drop commit 1; rewrite `cli.py` as five lines calling `graph.ainvoke` and printing `result["answer"]`. Keeps the only non-SSE entrypoint and keeps `state["answer"]` honest. | Round 5 settled deletion, and this exact counter-proposal was put to the user and not taken. Recorded, not reopened. |
| D-cheap-2 | Halve commit 4: hardcode the rate-limit numbers, leave `CORS_ALLOW_ORIGINS` env-readable, since it is the one knob that changes when the app gets a real domain and hardcoding it forces a rebuild. | Round 7 settled option 2, and `CLAUDE.md`'s config rule is hardcoded dataclasses rather than env-parsed getters. Keeping one env parser to save one rebuild reintroduces the pattern the rule exists to prevent. |

### Checked against the external reference the user supplied

The user asked for the plan to be verified against `atalupadhyay.wordpress.com/2026/01/02/fastapi-langgraph-building-production-ready-ai-apis`. It was fetched and read in full. It is an introductory tutorial, and it does not reach the parts of this plan that carry risk.

**Silent on everything commit 8 turns on.** The article never streams. Its only pipeline call is `result = graph.invoke(graph_input)`, a synchronous call, and it contains no `stream_mode`, no `astream`, no `astream_events`, no Server-Sent Events, no token extraction, no content-block handling, and no node-boundary or progress events. It therefore verifies nothing about `stream_mode="messages"`, the `langgraph_node` filter, `BaseMessage.text()`, or the inferred progress frames. Those remain verified only by the runtime checks recorded in §1.

One thing in it is worth not copying: that `graph.invoke` sits inside an `async def` endpoint, where a blocking call stalls the event loop for the whole process. This repo is already correct on that point and stays correct.

**Corroborates two plan decisions.**

- *Graph construction separated from the delivery layer.* The article builds the graph in its own module, compiles it at module scope, and has the FastAPI module import the compiled object. That is the shape of commit 8 exactly: `graph.py` constructs, `api.py` imports `graph`.
- *CORS origins hardcoded in application code.* Its CORS block writes the allowed origin as a literal, with no environment read. That is commit 4, and it undercuts the reviewer objection that `CORS_ALLOW_ORIGINS` should stay env-readable.

**Leans against three plan choices, none strongly enough to change them.**

- *It keeps a plain synchronous JSON endpoint as the primary route.* Commit 2 deletes this repo's equivalent. The article gives no argument for the route beyond it being the only one it implements, and it has no streaming route to weigh against. Restates finding D-cheap-1 without adding evidence; decision unchanged.
- *It recommends `slowapi` with a `@limiter.limit("10/minute")` decorator* rather than a hand-rolled store. Round 7 settled on keeping the existing limiter. Worth noting that `slowapi`'s default in-memory backend is also per-process, so adopting it would not fix the flagged multi-worker gap either.
- *It logs failures and re-raises*, and recommends INFO-level logging of request processing. This plan's `database.py` keeps a bare `except: pass` with no logger, and records no failed runs anywhere. That is an external voice on the same side as finding D6 and the brainstorm's own flag. The decision was settled twice and is held, but the count of independent objections to it is now three.

**One flag strengthened.** The article recommends running multiple worker processes in production. Neither `app/Dockerfile`, the root `Dockerfile`, nor either compose file passes `--workers` today, so the app runs one worker and the in-process rate limiter is sound. If anyone follows that advice, the effective rate limit silently multiplies by the worker count and each worker keeps its own unbounded client dictionary. The brainstorm carried this as a flag; it should be re-read before any worker count above one.

**Net effect on the plan: none.** No commit, code block, test, or rollout note changed as a result of this source.

### Still open

1. **The `location` column drop.** The rollback trap above is new information that postdates the round-16 decision. Worth one word from the user before commit 6.
2. **`BaseMessage.text()` versus `_chunk_text`.** This plan overrides a settled decision on evidence the brainstorm did not have. Flagged rather than assumed.
3. **The reference template could not be verified.** GitHub was unreachable from the review environment, so no reviewer could confirm that `wassim249/fastapi-langgraph-agent-production-ready-template` has the shape the brainstorm attributes to it. One structural caution regardless: that template is a chat agent whose state carries a `messages` list under an `add_messages` reducer, while `PipelineState` has `query`, `sources`, and `answer` and no messages key. Only the streaming loop transfers. Treat any further "the template does X" argument as unverified.
