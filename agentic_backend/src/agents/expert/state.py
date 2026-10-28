"""The expert agent's pipeline state."""

from __future__ import annotations

from typing import TypedDict

from models import Source
from shared.text import squash_whitespace


class PipelineState(TypedDict):
    """LangGraph state. Four keys, no reducers, no concurrent writers."""

    query: str
    search_query: str
    sources: list[Source]
    answer: str


def build_initial_pipeline_state(
    query: str, search_query: str | None = None
) -> PipelineState:
    """Return the initial state for one request."""
    normalized = squash_whitespace(query or "")
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {
        "query": normalized,
        "search_query": squash_whitespace(search_query or "") or normalized,
        "sources": [],
        "answer": "",
    }
