"""FastAPI application for the GeopoliticAI pipeline."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from config import init_environment, require_env
from graph import run_pipeline

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
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def _read_positive_int_env(var_name: str, default: int) -> int:
    raw = os.getenv(var_name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


RATE_LIMIT_REQUESTS = _read_positive_int_env(
    "API_RATE_LIMIT_REQUESTS",
    DEFAULT_RATE_LIMIT_REQUESTS,
)
RATE_LIMIT_WINDOW_SECONDS = _read_positive_int_env(
    "API_RATE_LIMIT_WINDOW_SECONDS",
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_environment()
    require_env()
    yield


app = FastAPI(title="GeopoliticAI API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class RunPipelineRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="Query to analyze",
    )
    infosphere: Literal["english", "polish"] = Field(
        "english", description="Which infosphere sources to use: english or polish"
    )

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Query must not be empty.")
        return cleaned


class RunPipelineResponse(BaseModel):
    output: str


def _sanitize_output(text: str) -> str:
    """Ensure the response contains only valid UTF-8 characters."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _resolve_client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_rate_limit(request: Request) -> None:
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
                detail=(
                    f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests per "
                    f"{RATE_LIMIT_WINDOW_SECONDS} seconds."
                ),
            )
        timestamps.append(now)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run_pipeline", response_model=RunPipelineResponse)
def run_pipeline_endpoint(
    payload: RunPipelineRequest,
    request: Request,
) -> RunPipelineResponse:
    _enforce_rate_limit(request)
    try:
        output = run_pipeline(payload.query, infosphere=payload.infosphere)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunPipelineResponse(output=_sanitize_output(output))
