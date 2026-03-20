from __future__ import annotations

from models import PipelineState, build_initial_pipeline_state, normalize_language


def ingest_request(state: PipelineState) -> PipelineState:
    query = " ".join(str(state.get("query", "")).split())
    if not query:
        raise ValueError("Query must not be empty.")

    language = normalize_language(state.get("language", "english"))
    max_loops = state.get("max_loops", 2)
    baseline = build_initial_pipeline_state(
        query,
        language=language,
        max_loops=max_loops,
    )
    updates = {key: value for key, value in baseline.items() if key not in state}
    updates["query"] = query
    updates["language"] = language
    updates["max_loops"] = max(int(max_loops), 0)
    return updates
