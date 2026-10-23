"""FastAPI application for the GeopoliticAI orchestrator agent."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Annotated, Any, AsyncGenerator

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.base import TTLConfig
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from agents.orchestrator import (
    build_graph,
    build_initial_orchestrator_state,
    build_runtime_config,
)
from agents.orchestrator import graph as _default_graph
from agents.reporter import classify_resume_intent
from auth import Identity, require_identity
from config import (
    DAILY_RESEARCH_TURNS,
    FOOTER_PREFIX,
    bind_log_context,
    init_environment,
    require_env,
)
from config import (
    MAX_ANSWER_CHARS as _MAX_ANSWER_CHARS,
)
from db.web.sql import (
    MAX_THREAD_ID_LENGTH,
    claim_thread,
    is_staff,
    list_threads,
    owns_thread,
    quota_used,
    title_from,
)
from frames import (
    NODE_EVENT,
    ErrorFrame,
    NoticeEvent,
    PauseFrame,
    ProgressFrame,
    ResultFrame,
    TokenFrame,
    encode_frame,
)
from models import (
    PipelineError,
    QuotaExceededError,
    ReportNotPendingError,
    squash_whitespace,
)
from quota import Charge, charge_turn, refund_turn
from tracing import bind_trace_user, init_tracing

logger = logging.getLogger(__name__)

# Explicit msgpack allow-list (POLI-16): the expert subgraph checkpoints
# `models.Source`; every other custom type is refused rather than rebuilt.
# LangChain messages and primitives are always allowed.
CHECKPOINT_SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("models", "Source")])

# The store holds only the deep forecaster's cached video notes (plan unit 09).
# Every item expires 30 days after it is written, as the privacy page says:
# reads never refresh it, and an expired item is never returned, even before
# the hourly sweep deletes it. The TTL lives here, not in `aput`, because the
# in-memory store the tests use has no TTL support.
STORE_TTL: TTLConfig = {
    "default_ttl": 30 * 24 * 60,
    "refresh_on_read": False,
    "omit_expired": True,
    "sweep_interval_minutes": 60,
}

# Hardcoded the way `LLMSettings` is hardcoded: edited here, never read from
# the environment.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8082",
    "http://localhost:3001",
]
MAX_QUERY_LENGTH = 2_000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TRACKED_CLIENTS = 10_000
THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]+$"

# Re-exported module attribute, not an import alias: the transport cap comes
# from `config.py`, and the checkpointer tests read `api.MAX_ANSWER_CHARS`.
MAX_ANSWER_CHARS = _MAX_ANSWER_CHARS
ThreadIdPath = Annotated[
    str,
    Path(min_length=1, max_length=MAX_THREAD_ID_LENGTH, pattern=THREAD_ID_PATTERN),
]

# The two frames the delivery layer owns, because both are facts about
# delivery rather than about a node: this one fires before the graph is
# touched at all (so it survives a failure inside `_turn_input`), and
# ANSWER_PROGRESS fires when the first character is about to reach the
# browser. Every *node*-scoped label now lives with its node, in that agent's
# `consts/progress.py`, and arrives here as a forwarded custom event.
THINKING_PROGRESS = ProgressFrame(node="supervisor", label="Thinking...")
ANSWER_PROGRESS = ProgressFrame(node="answer", label="Writing the answer...")

# `supervisor` answers a chat turn: it returns the answer whole as one
# `AIMessage`. Its other `AIMessage`, the footer after a tool, already reached
# the browser as a notice and is skipped by its `FOOTER_PREFIX`.
#
# `write` is the reporter's composing node. Its streamed chunks are the report;
# without it here the report never reaches the browser, and the `_ReportStarted`
# event that puts a Download .md button on the answer is derived from the same
# tag.
#
# `"tools"` must NEVER be added to this set, and neither may any node of a
# specialist: the reporter's refusal, cancel and revision-cap paths, the deep
# expert and the forecaster deliver their text as a `notice` from inside their
# tool, so adding their node would print it twice. No forecaster node may be
# named `answer`, `supervisor` or `write` for the same reason.
ANSWER_NODES = frozenset({"answer", "supervisor", "write"})

# `other` — a chat answer from the supervisor — is absent on purpose (Q5b):
# chat turns stay free. The supervisor does not re-run on a resume (the resume
# re-enters `tools`), so approving or revising a pending report does not count
# again: one report is one count, taken when it was requested, and the
# reporter's own revision cap bounds the rounds.
# `deep` spends DEEP_RESEARCH_TURN_COST units instead of one (brainstorm Q3),
# and `quota.charge_turn` looks up what each destination costs.
RESEARCH_DESTINATIONS = frozenset({"geopolitical", "deep", "forecast", "report"})
# The checkpointer names its tables unqualified in both its DDL and its
# queries, so search_path is the only way to put them anywhere but `public`.
# `agentic` first means setup() creates there; `public` second means
# db/web/sql.py still resolves Django's tables. Verified against
# langgraph-checkpoint-postgres 3.1.2, whose package contains no schema support.
POSTGRES_SEARCH_PATH = "agentic,public"
POSTGRES_CONNECTION_KWARGS: dict[str, Any] = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
    # Spaced form: libpq documents `options=-c name=value`. The concatenated
    # `-cname=value` happens to work because the backend arg parser is
    # getopt-based, but that is incidental, and this setting is the single
    # lever the whole schema design rests on.
    "options": f"-c search_path={POSTGRES_SEARCH_PATH}",
}
POSTGRES_POOL_MIN_SIZE = 1
POSTGRES_POOL_MAX_SIZE = 10

graph: Any = _default_graph

_rate_limit_store: dict[str, deque[float]] = {}
_rate_limit_lock = Lock()


@dataclass(frozen=True)
class _Counted:
    """the supervisor routed the turn to a research branch."""

    destination: str | None


@dataclass(frozen=True)
class _ReportStarted:
    """The reporter's `write` node began streaming the report."""


StreamEvent = (
    ProgressFrame | PauseFrame | NoticeEvent | TokenFrame | _Counted | _ReportStarted
)


async def _require_migrated_checkpointer_schema(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
) -> None:
    """Refuse to start when the checkpointer tables have not been migrated yet.

    This runs BEFORE `setup()`, and the ordering is the entire point.
    `CREATE TABLE IF NOT EXISTS` resolves to the first schema in `search_path`
    and checks existence only THERE — it does not check visibility. So calling
    `setup()` while the tables are still in `public` does not find them: it
    builds a complete second, empty set in `agentic`, every thread's history
    becomes invisible to unqualified reads, and
    `0002_checkpointer_to_agentic` then refuses to move anything because both
    copies exist. Verified by execution against Postgres 16.

    Checking first costs one query and makes that state unreachable. On a fresh
    database neither table exists and this passes.

    The same query also requires `current_schema()` to be `agentic`, which is
    where `setup()`'s unqualified `CREATE TABLE` lands. It is not when the
    `agentic` schema does not exist yet (Postgres skips missing schemas in
    `search_path`) or when the pool's `options` do not reach the connection;
    either way `setup()` would build a fresh set in `public`.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT to_regclass('public.checkpoints') AS stray,"
            " current_schema() AS target"
        )
        row = await cursor.fetchone() or {}
    if row.get("stray") is not None:
        raise RuntimeError(
            "public.checkpoints still exists, so the checkpointer schema has "
            "not been migrated. Run `make migrate-agentic` BEFORE starting "
            "this service. Starting first creates an empty second set of "
            "tables in `agentic` and hides the real history."
        )
    if row.get("target") != "agentic":
        raise RuntimeError(
            f"setup() would create the checkpointer tables in {row.get('target')!r}, "
            "not `agentic`: either the schema does not exist yet (run "
            "`make migrate-agentic`) or the pool's search_path is not reaching "
            "the connection."
        )


async def _assert_agentic_schema(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
) -> None:
    """Confirm both `setup()` calls put their tables where `search_path` should have.

    Cheap second assertion. If this fires, the pool's `options` are not
    reaching the connection.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT to_regclass('agentic.checkpoints') AS checkpoints,"
            " to_regclass('agentic.store') AS store"
        )
        row = await cursor.fetchone() or {}
    for table in ("checkpoints", "store"):
        if row.get(table) is None:
            raise RuntimeError(
                f"agentic.{table} does not exist after setup(): the pool's "
                "search_path is not reaching the connection."
            )


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
    store: AsyncPostgresStore | None = None
    try:
        checkpointer = AsyncPostgresSaver(pool, serde=CHECKPOINT_SERDE)
        await _require_migrated_checkpointer_schema(pool)
        await checkpointer.setup()
        # Built here, not at import: it captures the running loop. Same pool,
        # so the guard above also decides where its tables land.
        store = AsyncPostgresStore(pool, ttl=STORE_TTL)
        await store.setup()
        await _assert_agentic_schema(pool)
        await store.start_ttl_sweeper()
        graph = build_graph(checkpointer=checkpointer, store=store)
        # The thread/quota endpoints and the identity dependencies reach the
        # pool the checkpointer already shares; no second pool is opened.
        _app.state.pool = pool
        yield
    finally:
        graph = _default_graph
        # A sweeper stuck on the database must not skip closing the pool
        # (review thread, #151): bounded wait, and the pool closes in its own
        # finally, whatever the sweeper did.
        if store is not None:
            try:
                async with asyncio.timeout(5.0):
                    await store.stop_ttl_sweeper()
            except TimeoutError:
                logger.warning(
                    "the TTL sweeper did not stop within 5 s; closing the pool anyway"
                )
        try:
            await pool.close()
        except RuntimeError:
            logger.warning("the pool was already closed", exc_info=True)


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
        pattern=THREAD_ID_PATTERN,
        description="Conversation thread this turn belongs to",
    )

    @field_validator("query", "resume")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = squash_whitespace(value)
        if not cleaned:
            raise ValueError("Must not be empty.")
        return cleaned

    @model_validator(mode="after")
    def _exactly_one(self) -> RunPipelineRequest:
        if (self.query is None) == (self.resume is None):
            raise ValueError("Provide exactly one of `query` or `resume`.")
        return self


def _resolve_client_id(request: Request, identity: Identity | None = None) -> str:
    """Resolve a rate-limit key: the authenticated user, else the client address.

    nginx appends the connecting peer as the last `X-Forwarded-For` entry, so
    the right-most value is the address this request actually came from. Taking
    the first entry instead would let a caller spoof the id and rotate it to
    dodge the rate limit.

    Keyed on the authenticated user id when there is one (§7, Q17): a signed-in
    caller must not be able to rotate the forwarded header to dodge their
    bucket. The unauthenticated fallback keeps the spoofing note above: a
    header-based id is spoofable, and the daily quota in Postgres is the real
    bound on an authenticated caller. ponytail: the window is in-process, so
    with more than one uvicorn worker the per-minute limit multiplies by the
    worker count; the daily quota backstops it.
    """
    if identity is not None:
        return f"user:{identity.user_id}"
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


def _enforce_rate_limit(request: Request, identity: Identity | None = None) -> None:
    """Apply the in-process per-client rate limit."""
    now = time.monotonic()
    client_id = _resolve_client_id(request, identity)
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


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    """Return a simple health status."""
    return {"status": "ok"}


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
    `supervisor`, routes normally, and supersedes the stale `tools` task —
    afterwards `next == ()` and `interrupts == ()`, and the new turn is answered
    on the first try. Q11 is therefore the default behaviour and needs no
    mechanism.

    The brainstorm's probe #5 said the opposite, but it was measured on a
    single top-level node calling `interrupt()`, where the pending task is the
    only task there is. That result does not transfer to
    `START -> supervisor -> tools`.

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
) -> AsyncGenerator[StreamEvent, None]:
    """Run the orchestrator graph, yielding typed stream events.

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
    below: a custom event is a frame model or a dict that `NODE_EVENT` accepts,
    and `message, metadata = data` would raise on the first one.
    """
    config = build_runtime_config(thread_id=thread_id)
    streamed_nodes: set[str] = set()
    counted = False
    async for namespace, mode, data in graph.astream(
        graph_input,
        config=config,
        stream_mode=["custom", "updates", "messages"],
        subgraphs=True,
    ):
        if mode == "custom":
            try:
                event = NODE_EVENT.validate_python(data)
            except ValidationError:
                # Not a frame a node writes: a custom event this layer does not
                # know, or a malformed fake. Dropped here, so `_generate` never
                # sees it.
                continue
            # A branch that delivers the turn's answer whole instead of
            # streaming it: the reporter's refusal, cancel and revision-cap
            # paths, and the deep expert's and the deep forecaster's finished
            # answers. It goes out as a token, not as a frame of its own, because
            # it *is* the answer: it has to reach `parts`, the `MAX_ANSWER_CHARS`
            # accounting and `result.output` like any other. It is also the only
            # custom payload that may contain model-produced text, which is
            # exactly why it does not take the verbatim-forward path.
            if isinstance(event, NoticeEvent) and not event.text:
                continue
            yield event
            continue
        if mode == "updates":
            if namespace or not isinstance(data, dict):
                continue
            decision = data.get("supervisor")
            if not counted and isinstance(decision, dict):
                destination = decision.get("destination")
                if destination in RESEARCH_DESTINATIONS:
                    counted = True
                    yield _Counted(destination=destination)
            interrupts = data.get("__interrupt__")
            if interrupts:
                yield PauseFrame.model_validate(interrupts[0].value)
            continue
        message, metadata = data
        node = metadata.get("langgraph_node")
        if node not in ANSWER_NODES:
            continue
        if not isinstance(message, AIMessage):
            continue
        # A node that streams chunks also returns the completed message, which
        # would repeat the answer. The supervisor's completed footer already
        # arrived as a notice event; its completed chat answer is the only
        # copy, so it is forwarded as tokens.
        if message.__class__ is AIMessage and (
            node in streamed_nodes
            or (node == "supervisor" and message.text.startswith(FOOTER_PREFIX))
        ):
            continue
        text = message.text
        if text:
            if node == "write" and not streamed_nodes:
                # Only the reporter's composing node produces a downloadable
                # report; a refusal or a chat answer must not get the button.
                yield _ReportStarted()
            streamed_nodes.add(node)
            yield TokenFrame(content=text)


@router.post("/run_pipeline/stream")
async def run_pipeline_stream_endpoint(
    payload: RunPipelineRequest,
    request: Request,
    identity: Identity = Depends(require_identity),
) -> StreamingResponse:
    """Run the pipeline and stream progress, pause, and answer frames over SSE."""
    bind_log_context(thread_id=payload.thread_id, user_id=identity.user_id)
    bind_trace_user(identity.user_id)
    _enforce_rate_limit(request, identity)
    # No checkpoint read happens here: see `_turn_input`. The rate limit stays
    # pre-stream because it is the one failure that must not commit a 200.
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = request.app.state.pool
    # A resume can never be a thread's first turn: it belongs to a report the
    # endpoint already created, so it only verifies ownership — never upsert-
    # ing means a stale or hand-crafted resume cannot mint a ghost thread with
    # an empty title. A query owns the upsert-then-verify path: `ON CONFLICT
    # DO NOTHING` cannot tell the first turn from a later one in one round
    # trip, so the owner is read back.
    # No pre-routing quota check here: before the supervisor runs, the endpoint
    # cannot tell a chargeable research turn from a free chat turn or a report
    # resume (§7 S2), and a door check that guesses would 429 turns that cost
    # nothing — stranding a pending report forever. `increment_quota` in the
    # counted branch below is the sole authority, refusing a research turn as
    # a mid-stream 429 error frame.
    if payload.resume is not None:
        owned = await owns_thread(
            pool, thread_id=payload.thread_id, user_id=identity.user_id
        )
    else:
        owned = await claim_thread(
            pool,
            thread_id=payload.thread_id,
            user_id=identity.user_id,
            title=title_from(payload.query) if payload.query else "",
        )
    if not owned:
        raise HTTPException(status_code=403, detail="That conversation is not yours.")

    async def _generate() -> AsyncGenerator[str, None]:
        parts: list[str] = []
        consumed = 0
        paused = False
        is_report = False
        clipped = False
        # What this turn took from the user's own counter, and from which quota
        # day; None until `charge_turn` succeeds. Every error frame below refunds
        # it (brainstorm 2026Oct16 Q1); a disconnect does not.
        charge: Charge | None = None

        async def refund() -> None:
            if charge is not None:
                await refund_turn(pool, user_id=identity.user_id, charge=charge)

        try:
            yield encode_frame(THINKING_PROGRESS)
            # The checkpoint read and the intent call happen here, not in the
            # endpoint, so their failures arrive as SSE `error` frames like
            # every other pipeline failure.
            graph_input = await _turn_input(payload)
            # Nothing here inspects `payload.resume`. The nodes emit their own
            # progress, so a revise resume is announced by `outline` and an
            # approve resume by `write`, on the same code path as a first turn.
            async for event in _astream_answer(graph_input, payload.thread_id):
                match event:
                    case ProgressFrame():
                        # Forwarded as the node wrote it: a literal from an
                        # agent's `consts/progress.py` (§1).
                        yield encode_frame(event)
                    case PauseFrame():
                        paused = True
                        yield encode_frame(event)
                    case _ReportStarted():
                        is_report = True
                    case _Counted(destination=destination):
                        charge = await charge_turn(
                            pool, user_id=identity.user_id, destination=destination
                        )
                    case TokenFrame(content=text) | NoticeEvent(text=text):
                        if (
                            isinstance(event, TokenFrame)
                            and not parts
                            and not is_report
                        ):
                            # ANSWER_PROGRESS is suppressed on two paths. The report
                            # path already announced itself from the `write` node with
                            # a better label, and appending "Writing the answer..."
                            # after it would leave that as the *active* step for the
                            # whole report — `progressLog` is an accumulating list that
                            # never dedupes (`frontend/index.html:359-369`). And a
                            # `notice` arrives whole — a refusal, a cancellation, or a
                            # finished deep analysis — so nothing is left to announce
                            # as being written.
                            yield encode_frame(ANSWER_PROGRESS)
                        remaining = MAX_ANSWER_CHARS - consumed
                        if remaining <= 0:
                            # Upstream is still drained (this is `continue`, not `break`)
                            # so checkpoint writes finish — the pre-existing behaviour.
                            clipped = True
                            continue
                        chunk = text[:remaining]
                        if len(chunk) < len(text):
                            clipped = True
                        parts.append(chunk)
                        consumed += len(chunk)
                        yield encode_frame(TokenFrame(content=chunk))
            output = "".join(parts).strip()
            if not output:
                if paused:
                    # A pause is a complete, successful turn: the run stopped on
                    # purpose and the browser already has the outline.
                    return
                await refund()
                yield encode_frame(
                    ErrorFrame(
                        status=502, message="The model returned an empty answer."
                    )
                )
                return
            yield encode_frame(
                ResultFrame(
                    output=output,
                    kind="report" if is_report else "answer",
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
                    truncated=clipped,
                )
            )
        except QuotaExceededError as exc:
            # A refused turn: nothing was charged to the user, nothing to refund,
            # and no warning log (it is not a failure of the pipeline).
            yield encode_frame(ErrorFrame(status=exc.status, message=str(exc)))
        except PipelineError as exc:
            logger.warning("Streaming pipeline failed: %s", exc)
            await refund()
            yield encode_frame(ErrorFrame(status=exc.status, message=str(exc)))
        except Exception:
            logger.exception("Streaming pipeline failed unexpectedly.")
            await refund()
            yield encode_frame(
                ErrorFrame(
                    status=500,
                    message="An unexpected error occurred. Please try again.",
                )
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _thread_messages(thread_id: str) -> list[dict[str, str]]:
    """Read one conversation live from the checkpointer (Q6).

    The checkpointer's message text lives in msgpack-serialized BYTEA, so the
    only thing that can read it is code holding the graph — never an admin
    pointed at the table (brainstorm §2.4). `aget_state` is that code.
    """
    if getattr(graph, "checkpointer", None) is None:
        return []
    snapshot = await graph.aget_state(build_runtime_config(thread_id=thread_id))
    rendered: list[dict[str, str]] = []
    for msg in snapshot.values.get("messages", []):
        if msg.type == "human":
            rendered.append({"role": "user", "text": msg.text})
        elif isinstance(msg, ToolMessage):
            text = (
                msg.artifact.get("text", msg.content)
                if isinstance(msg.artifact, dict)
                else msg.content
            )
            rendered.append({"role": "assistant", "text": str(text)})
        elif isinstance(msg, AIMessage) and msg.text and not msg.tool_calls:
            if msg.text.startswith(FOOTER_PREFIX) and rendered:
                rendered[-1]["text"] += msg.text
            else:
                rendered.append({"role": "assistant", "text": msg.text})
    return rendered


@router.get("/threads")
async def list_threads_endpoint(
    request: Request, identity: Identity = Depends(require_identity)
) -> dict[str, Any]:
    """Return the caller's conversations and today's quota, for the sidebar."""
    bind_log_context(user_id=identity.user_id)
    pool = request.app.state.pool
    return {
        "threads": [
            row.__dict__ for row in await list_threads(pool, user_id=identity.user_id)
        ],
        "quota": {
            "used": await quota_used(pool, user_id=identity.user_id),
            "limit": DAILY_RESEARCH_TURNS,
        },
    }


@router.get("/threads/{thread_id}")
async def read_thread_endpoint(
    thread_id: ThreadIdPath,
    request: Request,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    """Return one of the caller's own conversations."""
    bind_log_context(thread_id=thread_id, user_id=identity.user_id)
    # Rate-limited like the streaming route: this reads a checkpoint and
    # deserializes an entire conversation, so it is not free. The daily quota
    # (unit 6) deliberately does not cover it: reading your own history must
    # not cost research turns.
    _enforce_rate_limit(request, identity)
    pool = request.app.state.pool
    if not await owns_thread(pool, thread_id=thread_id, user_id=identity.user_id):
        raise HTTPException(status_code=403, detail="That conversation is not yours.")
    return {"thread_id": thread_id, "messages": await _thread_messages(thread_id)}


@router.get("/admin/threads/{thread_id}")
async def admin_read_thread_endpoint(
    thread_id: ThreadIdPath,
    request: Request,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    """Return any conversation, for a staff user (Q6, Q17b)."""
    bind_log_context(thread_id=thread_id, user_id=identity.user_id)
    _enforce_rate_limit(request, identity)
    # Re-read from Postgres rather than trusting a claim: a token minted before
    # staff was revoked stays valid for its full 15 minutes otherwise.
    if not await is_staff(request.app.state.pool, user_id=identity.user_id):
        raise HTTPException(status_code=403, detail="Staff only.")
    return {"thread_id": thread_id, "messages": await _thread_messages(thread_id)}


app.include_router(router)
