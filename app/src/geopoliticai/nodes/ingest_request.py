"""Request ingestion and normalization node."""

from __future__ import annotations

from typing import Any

from geopoliticai.models import (
    PipelineState,
    build_initial_pipeline_state,
    normalize_language,
)


def ingest_request(state: PipelineState) -> dict[str, Any]:
    """Normalize the request and fill any missing state defaults."""
    query = " ".join(str(state.get("query", "")).split())
    if not query:
        raise ValueError("Query must not be empty.")

    language = normalize_language(state.get("language", "english"))
    baseline = build_initial_pipeline_state(
        query,
        language=language,
    )
    updates = {key: value for key, value in baseline.items() if key not in state}
    updates["query"] = query
    updates["language"] = language
    return updates
