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

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import database
from agents.expert import NODE_LABELS, astream_pipeline
from config import init_environment, require_env
from models import LLMInvocationError, PipelineError
from tracing import init_tracing

logger = logging.getLogger(__name__)

# Hardcoded the way `LLMSettings` is hardcoded: edited here, never read from
# the environment.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5173",
]
MAX_QUERY_LENGTH = 2_000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60

_rate_limit_store: dict[str, deque[float]] = defaultdict(deque)
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
    """Resolve a client address, honoring the first forwarded address."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_rate_limit(request: Request) -> None:
    """Apply the in-process per-client rate limit."""
    now = time.monotonic()
    client_id = _resolve_client_id(request)
    with _rate_limit_lock:
        timestamps = _rate_limit_store[client_id]
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS} seconds.",
            )
        timestamps.append(now)


_FRONTEND_HTML = os.getenv("FRONTEND_HTML_PATH", "/app/frontend/index.html")
_FRONTEND_ASSETS = os.path.join(os.path.dirname(_FRONTEND_HTML), "assets")
if os.path.isdir(_FRONTEND_ASSETS):
    app.mount(
        "/assets", StaticFiles(directory=_FRONTEND_ASSETS), name="frontend-assets"
    )


@app.get("/")
async def serve_frontend() -> FileResponse:
    """Serve the static frontend shell when available."""
    if os.path.exists(_FRONTEND_HTML):
        return FileResponse(_FRONTEND_HTML)
    raise HTTPException(status_code=404, detail="Frontend not available")


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    """Return a simple health status."""
    return {"status": "ok"}


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
            await database.log_run(payload.query, client_id, output)
            yield _sse({"type": "result", "output": output})
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


app.include_router(router)
