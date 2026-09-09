"""FastAPI application for the GeopoliticAI orchestrator agent."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, AsyncGenerator

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, field_validator, model_validator

from agents.orchestrator import (
    build_graph,
    build_initial_orchestrator_state,
    build_runtime_config,
)
from agents.orchestrator import graph as _default_graph
from agents.reporter import classify_resume_intent
from config import init_environment, require_env
from models import PipelineError, ReportNotPendingError
from tracing import init_tracing

logger = logging.getLogger(__name__)

# Hardcoded the way `LLMSettings` is hardcoded: edited here, never read from
# the environment.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8082",
    "http://localhost:3001",
]
MAX_QUERY_LENGTH = 2_000
MAX_THREAD_ID_LENGTH = 100
MAX_ANSWER_CHARS = 50_000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TRACKED_CLIENTS = 10_000

# The two frames the delivery layer owns, because both are facts about
# delivery rather than about a node: this one fires before the graph is
# touched at all (so it survives a failure inside `_turn_input`), and
# ANSWER_PROGRESS fires when the first character is about to reach the
# browser. Every *node*-scoped label now lives with its node, in that agent's
# `consts/progress.py`, and arrives here as a forwarded custom event.
THINKING_PROGRESS = {"node": "classify", "label": "Thinking..."}
ANSWER_PROGRESS = {"node": "answer", "label": "Writing the answer..."}

# `write` is the reporter's composing node. Its streamed chunks are the report;
# without it here the report never reaches the browser, and the `("kind",
# "report")` event that puts a Download .md button on the answer is derived from
# the same tag.
#
# `"reporter"` must NEVER be added to this set. Measured: on the refusal, cancel
# and revision-cap paths the orchestrator's `reporter` node returns an
# `AIMessage` that *also* arrives in `messages` mode tagged
# `langgraph_node == "reporter"` — and that same text already reaches the
# browser through the node's own `notice` custom event. Adding `"reporter"`
# here would print every refusal and cancellation twice.
ANSWER_NODES = frozenset({"answer", "chat", "write"})

POSTGRES_CONNECTION_KWARGS: dict[str, Any] = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}
POSTGRES_POOL_MIN_SIZE = 1
POSTGRES_POOL_MAX_SIZE = 10

graph: Any = _default_graph

_rate_limit_store: dict[str, deque[float]] = {}
_rate_limit_lock = Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize application resources; require a database for threads."""
    global graph
    init_environment()
    init_tracing()
    require_env()
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise ValueError(
            "DATABASE_URL is required: conversation threads are stored in Postgres."
        )
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        conninfo=db_url,
        min_size=POSTGRES_POOL_MIN_SIZE,
        max_size=POSTGRES_POOL_MAX_SIZE,
        kwargs=POSTGRES_CONNECTION_KWARGS,
        open=False,
    )
    await pool.open()
    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        graph = build_graph(checkpointer=checkpointer)
        yield
    finally:
        graph = _default_graph
        await pool.close()


app = FastAPI(title="GeopoliticAI API", version="1.0.0", lifespan=lifespan)
router = APIRouter(prefix="/api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class RunPipelineRequest(BaseModel):
    """Request payload for one conversation turn, or one answer to a pause.

    Exactly one of `query` and `resume` is set. `query` starts a turn; `resume`
    is text the user typed while a report outline was waiting for a decision.
    The two are separate fields rather than one because only the client knows
    which of the two it meant, and guessing from checkpoint state would make a
    stale browser tab silently answer a pause it never saw.

    Both fields carry the same `MAX_QUERY_LENGTH` cap and the same normalizer:
    a resume is user input arriving at the same trust boundary as a query.
    """

    query: str | None = Field(
        default=None, max_length=MAX_QUERY_LENGTH, description="A new conversation turn"
    )
    resume: str | None = Field(
        default=None,
        max_length=MAX_QUERY_LENGTH,
        description="A reply to a pending report outline",
    )
    thread_id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_THREAD_ID_LENGTH,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Conversation thread this turn belongs to",
    )

    @field_validator("query", "resume")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Must not be empty.")
        return cleaned

    @model_validator(mode="after")
    def _exactly_one(self) -> RunPipelineRequest:
        if (self.query is None) == (self.resume is None):
            raise ValueError("Provide exactly one of `query` or `resume`.")
        return self


def _resolve_client_id(request: Request) -> str:
    """Resolve a client address, honoring the address appended by nginx.

    nginx appends the connecting peer as the last `X-Forwarded-For` entry, so
    the right-most value is the address this request actually came from. Taking
    the first entry instead would let a caller spoof the id and rotate it to
    dodge the rate limit.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _flush_stale_clients(now: float) -> None:
    """Drop clients whose request windows have fully drained.

    Keeps the in-process rate-limit store from growing without bound as new
    client ids arrive.
    """
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    for client_id, timestamps in list(_rate_limit_store.items()):
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if not timestamps:
            del _rate_limit_store[client_id]


def _enforce_rate_limit(request: Request) -> None:
    """Apply the in-process per-client rate limit."""
    now = time.monotonic()
    client_id = _resolve_client_id(request)
    with _rate_limit_lock:
        timestamps = _rate_limit_store.get(client_id)
        if timestamps is None:
            if len(_rate_limit_store) >= MAX_TRACKED_CLIENTS:
                _flush_stale_clients(now)
                if len(_rate_limit_store) >= MAX_TRACKED_CLIENTS:
                    # Hard bound: evict the least recently seen client.
                    del _rate_limit_store[next(iter(_rate_limit_store))]
            timestamps = deque()
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS} seconds.",
            )
        timestamps.append(now)
        _rate_limit_store[client_id] = timestamps


_FRONTEND_HTML = os.getenv("FRONTEND_HTML_PATH", "/app/frontend/index.html")
_FRONTEND_ASSETS = os.path.join(os.path.dirname(_FRONTEND_HTML), "assets")
if os.path.isdir(_FRONTEND_ASSETS):
    app.mount(
        "/assets", StaticFiles(directory=_FRONTEND_ASSETS), name="frontend-assets"
    )


def _frontend_html_path() -> str:
    """Resolve the frontend shell at request time.

    The repo-root `.env`, which ``lifespan`` loads via ``init_environment()``,
    becomes available only after this module is imported, so the path must not be
    read at import time. The ``/assets`` mount above stays on the import-time
    default because a static mount cannot be re-resolved per request.
    """
    return os.getenv("FRONTEND_HTML_PATH", "/app/frontend/index.html")


@app.get("/")
async def serve_frontend() -> FileResponse:
    """Serve the static frontend shell when available."""
    html = _frontend_html_path()
    if os.path.exists(html):
        return FileResponse(html)
    raise HTTPException(status_code=404, detail="Frontend not available")


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    """Return a simple health status."""
    return {"status": "ok"}


def _sse(payload: dict[str, Any]) -> str:
    """Serialize one SSE data frame."""
    return f"data: {json.dumps(payload)}\n\n"


async def _pending_pause(thread_id: str) -> dict[str, Any] | None:
    """Return the outline a paused thread is waiting on, or None.

    Called only on the resume path (see `_turn_input`).

    `graph.checkpointer` is None under `make test` and `langgraph dev`, where
    `build_graph()` is used directly. Such a graph cannot hold a pause at all,
    so None is the true answer, not a degraded one — and `aget_state` would
    raise `ValueError("No checkpointer set")` if asked.

    `StateSnapshot.interrupts` and `Interrupt.value` are public fields of
    langgraph's own NamedTuples (`langgraph/types.py:248-266`), not internals.
    """
    if getattr(graph, "checkpointer", None) is None:
        return None
    snapshot = await graph.aget_state(build_runtime_config(thread_id=thread_id))
    interrupts = snapshot.interrupts
    if not interrupts:
        return None
    value = interrupts[0].value
    if isinstance(value, dict):
        return value
    return {"outline": [], "notice": str(value)}


async def _turn_input(payload: RunPipelineRequest) -> Any:
    """Decide what this request hands the graph: a resume, or a fresh turn.

    A plain turn needs no checkpoint read at all. **Measured on this graph's
    actual shape:** a state input arriving while a report is paused re-enters
    `classify`, routes normally, and supersedes the stale `reporter` task —
    afterwards `next == ()` and `interrupts == ()`, and the new turn is answered
    on the first try. Q11 is therefore the default behaviour and needs no
    mechanism.

    The brainstorm's probe #5 said the opposite, but it was measured on a
    single top-level node calling `interrupt()`, where the pending task is the
    only task there is. That result does not transfer to
    `START -> classify -> {expert|chat|reporter}`.

    An earlier draft of this plan cleared the pause explicitly with
    `aupdate_state(config, None, as_node="reporter")`. That call is deleted: it
    was one Postgres write, one failure mode, and one dependency on an
    undocumented `aupdate_state` behaviour, all to force something the graph
    already does.
    """
    if payload.resume is None:
        return build_initial_orchestrator_state(payload.query or "")
    # Only the resume path reads the checkpoint, so an ordinary chat or expert
    # turn does no extra database work and gains no new failure mode.
    pause = await _pending_pause(payload.thread_id)
    if pause is None:
        raise ReportNotPendingError(
            "This conversation has no report waiting for a decision."
        )
    intent = await classify_resume_intent(payload.resume, pause)
    if intent.action == "new_question":
        return build_initial_orchestrator_state(payload.resume)
    return Command(resume={"action": intent.action, "instruction": intent.instruction})


async def _astream_answer(
    graph_input: Any, thread_id: str
) -> AsyncGenerator[tuple[str, Any], None]:
    """Run the orchestrator graph, yielding progress, pause, kind and token events.

    `graph_input` is either an orchestrator state or a `Command(resume=...)`;
    both are graph inputs on the same thread id and neither changes the call.

    Three stream modes, three jobs — and they are filtered differently on
    purpose:

    * `custom` carries whatever a node chose to tell the browser. **The
      namespace filter must NOT be applied here.** Measured against langgraph
      1.0.1: a custom event emitted inside the `ainvoke`d reporter subgraph
      arrives at `ns=('reporter:<uuid>',)`, non-empty, because the child reuses
      the parent's stream writer through the ambient config and that writer
      computes its namespace from the child's own checkpoint namespace at call
      time. Reusing the `updates` filter here would drop every reporter
      progress frame with no error at all. Guarded by
      `test_report_progress_arrives_under_the_child_namespace`.
    * `updates` carries only `__interrupt__` now, and keeps the filter: the
      interrupt is emitted twice, once under the child namespace and once under
      an empty one, and this passes exactly one. Guarded by
      `test_report_branch_pauses_at_top_level_namespace`.
    * `messages` carries answer tokens, exactly as before.

    The `custom` branch must be dispatched **before** the `messages` unpacking
    below: a custom payload is a plain dict, and `message, metadata = data`
    would raise on the first one.
    """
    config = build_runtime_config(thread_id=thread_id)
    streamed_nodes: set[str] = set()
    async for namespace, mode, data in graph.astream(
        graph_input,
        config=config,
        stream_mode=["custom", "updates", "messages"],
        subgraphs=True,
    ):
        if mode == "custom":
            if not isinstance(data, dict):
                continue
            event_type = data.get("type")
            if event_type == "notice":
                # A branch that produced the turn's answer without a model call
                # (refusal, cancel, revision cap). It goes out as a token, not
                # as a frame of its own, because it *is* the answer: it has to
                # reach `parts`, the `MAX_ANSWER_CHARS` accounting and
                # `result.output` like any other. It is also the only custom
                # payload that may contain model-produced text, which is
                # exactly why it does not take the verbatim-forward path.
                text = str(data.get("text") or "")
                if text:
                    yield ("notice", text)
            elif isinstance(event_type, str):
                yield (event_type, data)
            continue
        if mode == "updates":
            if namespace or not isinstance(data, dict):
                continue
            interrupts = data.get("__interrupt__")
            if interrupts:
                yield ("pause", interrupts[0].value)
            continue
        message, metadata = data
        node = metadata.get("langgraph_node")
        if node not in ANSWER_NODES:
            continue
        if not isinstance(message, AIMessage):
            continue
        # Chat nodes emit provider chunks and then the completed message they
        # return. Once chunks have been forwarded, the completed message would
        # duplicate the answer; expert's nested completed message is tagged
        # with the parent node and is filtered above.
        if message.__class__ is AIMessage and node in streamed_nodes:
            continue
        text = message.text()
        if text:
            if node == "write" and not streamed_nodes:
                # Only the reporter's composing node produces a downloadable
                # report; a refusal or a chat answer must not get the button.
                yield ("kind", "report")
            streamed_nodes.add(node)
            yield ("token", text)


@router.post("/run_pipeline/stream")
async def run_pipeline_stream_endpoint(
    payload: RunPipelineRequest, request: Request
) -> StreamingResponse:
    """Run the pipeline and stream progress, pause, and answer frames over SSE."""
    _enforce_rate_limit(request)
    # No checkpoint read happens here: see `_turn_input`. The rate limit stays
    # pre-stream because it is the one failure that must not commit a 200.

    async def _generate() -> AsyncGenerator[str, None]:
        parts: list[str] = []
        consumed = 0
        paused = False
        is_report = False
        clipped = False
        try:
            yield _sse({"type": "progress", **THINKING_PROGRESS})
            # The checkpoint read and the intent call happen here, not in the
            # endpoint, so their failures arrive as SSE `error` frames like
            # every other pipeline failure.
            graph_input = await _turn_input(payload)
            # Nothing here inspects `payload.resume`. The nodes emit their own
            # progress, so a revise resume is announced by `outline` and an
            # approve resume by `write`, on the same code path as a first turn.
            async for kind, value in _astream_answer(graph_input, payload.thread_id):
                if kind == "progress":
                    # Forwarded verbatim: the node already wrote the whole
                    # frame. Every payload that reaches this line is a
                    # hardcoded literal in an agent's `consts/progress.py`;
                    # model- and user-produced text never takes this path (§1).
                    yield _sse(value)
                    continue
                if kind == "pause":
                    paused = True
                    yield _sse({"type": "pause", **value})
                    continue
                if kind == "kind":
                    is_report = True
                    continue
                if kind not in ("token", "notice"):
                    # An event kind this layer does not know. Ignoring it is
                    # what stops a future node's custom event from falling
                    # through to the slicing below, where `value[:remaining]`
                    # on a dict would kill the turn with a TypeError inside the
                    # SSE generator.
                    continue
                if kind == "token" and not parts and not is_report:
                    # ANSWER_PROGRESS is suppressed on two paths. The report
                    # path already announced itself from the `write` node with
                    # a better label, and appending "Writing the answer..."
                    # after it would leave that as the *active* step for the
                    # whole report — `progressLog` is an accumulating list that
                    # never dedupes (`frontend/index.html:359-369`). And a
                    # `notice` is not a model answer at all: it is a refusal or
                    # a cancellation, arriving whole, with nothing being
                    # written.
                    yield _sse({"type": "progress", **ANSWER_PROGRESS})
                remaining = MAX_ANSWER_CHARS - consumed
                if remaining <= 0:
                    # Upstream is still drained (this is `continue`, not `break`)
                    # so checkpoint writes finish — the pre-existing behaviour.
                    clipped = True
                    continue
                chunk = value[:remaining]
                if len(chunk) < len(value):
                    clipped = True
                parts.append(chunk)
                consumed += len(chunk)
                yield _sse({"type": "token", "content": chunk})
            output = "".join(parts).strip()
            if not output:
                if paused:
                    # A pause is a complete, successful turn: the run stopped on
                    # purpose and the browser already has the outline.
                    return
                yield _sse(
                    {
                        "type": "error",
                        "status": 502,
                        "message": "The model returned an empty answer.",
                    }
                )
                return
            yield _sse(
                {
                    "type": "result",
                    "output": output,
                    "kind": "report" if is_report else "answer",
                    # The transport cap is pre-existing and already clips long
                    # expert answers today. What is new is the download button,
                    # which would otherwise write a clipped file to disk under a
                    # name that looks complete. Say so instead.
                    #
                    # `clipped`, not `consumed >= MAX_ANSWER_CHARS`: a report of
                    # exactly 50,000 characters loses nothing, and the cheaper
                    # comparison would label it partial and save it to disk as
                    # `report-<date>-partial.md`. This flag is set only where
                    # characters were actually dropped.
                    "truncated": clipped,
                }
            )
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


app.include_router(router)
