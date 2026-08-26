"""The expert agent's pipeline state."""

from __future__ import annotations

from typing import TypedDict

from models import Source


class PipelineState(TypedDict):
    """LangGraph state. Three keys, no reducers, no concurrent writers."""

    query: str
    sources: list[Source]
    answer: str


def build_initial_pipeline_state(query: str) -> PipelineState:
    """Return the initial state for one request."""
    normalized = " ".join((query or "").split())
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {"query": normalized, "sources": [], "answer": ""}
