"""FastAPI application for the GeopoliticAI pipeline."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from geopoliticai.config import init_environment, require_env
from geopoliticai.graph import run_pipeline

app = FastAPI(title="GeopoliticAI API", version="1.0.0")


class RunPipelineRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Query to analyze")
    infosphere: str = Field(
        "english", description="Which infosphere sources to use: english or polish"
    )


class RunPipelineResponse(BaseModel):
    output: str


def _sanitize_output(text: str) -> str:
    """Ensure the response contains only valid UTF-8 characters."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


@app.on_event("startup")
def startup() -> None:
    init_environment()
    try:
        require_env()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run_pipeline", response_model=RunPipelineResponse)
def run_pipeline_endpoint(payload: RunPipelineRequest) -> RunPipelineResponse:
    try:
        output = run_pipeline(payload.query, infosphere=payload.infosphere)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunPipelineResponse(output=_sanitize_output(output))
