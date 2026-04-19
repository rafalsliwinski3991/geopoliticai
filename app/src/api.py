"""FastAPI application for the GeopoliticAI pipeline."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import AsyncGenerator, Literal

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import database
from config import init_environment, require_env
from graph import build_graph, run_pipeline
from models import build_initial_pipeline_state, normalize_language

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
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        await database.init_pool(db_url)
    yield
    await database.close_pool()


app = FastAPI(title="GeopoliticAI API", version="1.0.0", lifespan=lifespan)
router = APIRouter(prefix="/api")
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
        "polish", description="Which infosphere sources to use: english or polish"
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


_FRONTEND_HTML = os.getenv("FRONTEND_HTML_PATH", "/app/frontend/index.html")
_FRONTEND_ASSETS = os.path.join(os.path.dirname(_FRONTEND_HTML), "assets")

if os.path.isdir(_FRONTEND_ASSETS):
    app.mount("/assets", StaticFiles(directory=_FRONTEND_ASSETS), name="frontend-assets")


@app.get("/")
async def serve_frontend() -> FileResponse:
    if os.path.exists(_FRONTEND_HTML):
        return FileResponse(_FRONTEND_HTML)
    raise HTTPException(status_code=404, detail="Frontend not available")


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


_NODE_LABELS_PL: dict[str, str] = {
    "ingest_request": "Przetwarzam zapytanie...",
    "build_research_plan": "Buduję plan badań...",
    "search_left_pool": "Przeszukuję lewicowe źródła...",
    "search_center_pool": "Przeszukuję centrowe źródła...",
    "search_right_pool": "Przeszukuję prawicowe źródła...",
    "search_people_pool": "Przeszukuję profile osób...",
    "left_analyst": "Analizuję perspektywę lewicową...",
    "center_analyst": "Analizuję perspektywę centrową...",
    "right_analyst": "Analizuję perspektywę prawicową...",
    "people_analyst": "Analizuję profile osób...",
    "referee": "Weryfikuję treść raportu...",
    "referee_blocked_summary": "Podsumowuję blokadę...",
    "extract_claims": "Wyodrębniam twierdzenia...",
    "cross_check_facts": "Sprawdzam fakty krzyżowo...",
    "compose_final": "Komponuję raport końcowy...",
    "supervisor": "Finalizuję odpowiedź...",
}
_NODE_LABELS_EN: dict[str, str] = {
    "ingest_request": "Processing query...",
    "build_research_plan": "Building research plan...",
    "search_left_pool": "Searching left-leaning sources...",
    "search_center_pool": "Searching centrist sources...",
    "search_right_pool": "Searching right-leaning sources...",
    "search_people_pool": "Searching people profiles...",
    "left_analyst": "Analyzing left perspective...",
    "center_analyst": "Analyzing centrist perspective...",
    "right_analyst": "Analyzing right perspective...",
    "people_analyst": "Analyzing people profiles...",
    "referee": "Verifying report content...",
    "referee_blocked_summary": "Summarizing block...",
    "extract_claims": "Extracting claims...",
    "cross_check_facts": "Cross-checking facts...",
    "compose_final": "Composing final report...",
    "supervisor": "Finalizing answer...",
}


@router.post("/run_pipeline/stream")
async def run_pipeline_stream_endpoint(
    payload: RunPipelineRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    _enforce_rate_limit(request)
    client_id = _resolve_client_id(request)
    log_id = await database.log_prompt(payload.query, client_id)

    node_labels = _NODE_LABELS_PL if payload.infosphere == "polish" else _NODE_LABELS_EN
    empty_msg = (
        "Backend zwrócił pustą odpowiedź."
        if payload.infosphere == "polish"
        else "Backend returned an empty response."
    )
    unexpected_msg = (
        "Nieoczekiwany błąd: {}"
        if payload.infosphere == "polish"
        else "Unexpected error: {}"
    )

    async def _generate() -> AsyncGenerator[str, None]:
        try:
            graph = build_graph(infosphere=payload.infosphere)
            initial_state = build_initial_pipeline_state(
                payload.query,
                language=normalize_language(payload.infosphere),
            )
            seen_nodes: set[str] = set()
            final_output: str | None = None

            async for event in graph.astream_events(
                initial_state, version="v2"
            ):
                etype = event.get("event", "")
                node = event.get("metadata", {}).get(
                    "langgraph_node", ""
                )

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

                if (
                    etype == "on_chain_end"
                    and event.get("name") == "GeopoliticAI"
                ):
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict):
                        final_output = output.get("final_output")

            if final_output is not None:
                data = json.dumps(
                    {
                        "type": "result",
                        "output": _sanitize_output(final_output),
                    }
                )
                if log_id is not None:
                    await database.log_output(log_id, final_output)
            else:
                data = json.dumps({"type": "error", "message": empty_msg})
            yield f"data: {data}\n\n"

        except ValueError as exc:
            data = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {data}\n\n"
        except Exception as exc:
            msg = unexpected_msg.format(exc)
            data = json.dumps({"type": "error", "message": msg})
            yield f"data: {data}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/run_pipeline", response_model=RunPipelineResponse)
async def run_pipeline_endpoint(
    payload: RunPipelineRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> RunPipelineResponse:
    _enforce_rate_limit(request)
    client_id = _resolve_client_id(request)
    log_id = await database.log_prompt(payload.query, client_id)
    try:
        output = run_pipeline(payload.query, infosphere=payload.infosphere)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if log_id is not None:
        background_tasks.add_task(
            database.log_output, log_id, output
        )
    return RunPipelineResponse(output=_sanitize_output(output))


app.include_router(router)
