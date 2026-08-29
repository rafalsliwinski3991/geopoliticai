"""FastAPI application for the GeopoliticAI expert agent."""

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
from pydantic import BaseModel, Field, field_validator

import database
from agents.expert import build_initial_pipeline_state, build_runtime_config, graph
from config import init_environment, require_env
from models import PipelineError
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
MAX_ANSWER_CHARS = 50_000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TRACKED_CLIENTS = 10_000

SEARCH_PROGRESS = {
    "node": "search_and_fetch",
    "label": "Searching and reading sources...",
}
ANSWER_PROGRESS = {"node": "answer", "label": "Writing the answer..."}

_rate_limit_store: dict[str, deque[float]] = {}
_rate_limit_lock = Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and close optional application resources."""
    init_environment()
    init_tracing()
    require_env()
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        await database.init_pool(db_url)
    yield
    await database.close_pool()


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
    """Request payload for running the analysis pipeline."""

    query: str = Field(
        ..., min_length=1, max_length=MAX_QUERY_LENGTH, description="Query to analyze"
    )

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Query must not be empty.")
        return cleaned


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
        consumed = 0
        try:
            yield _sse({"type": "progress", **SEARCH_PROGRESS})
            async for text in _astream_answer(payload.query):
                if not parts:
                    yield _sse({"type": "progress", **ANSWER_PROGRESS})
                remaining = MAX_ANSWER_CHARS - consumed
                if remaining <= 0:
                    break
                chunk = text[:remaining]
                parts.append(chunk)
                consumed += len(chunk)
                yield _sse({"type": "token", "content": chunk})
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


app.include_router(router)
