"""Search pool helpers for populating lane-specific source lists."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from models import PipelineState, build_error_record
from nodes.runtime_config import runtime_infosphere_sources
from search import SearchExhaustedError, web_searcher


def _search_lane_pool(
    state: PipelineState,
    config: RunnableConfig | None,
    lane_key: str,
    state_key: str,
) -> dict[str, Any]:
    """Populate a single lane's sources via the web searcher."""
    infosphere_sources = runtime_infosphere_sources(state, config)
    try:
        sources = web_searcher(state, lane_key, infosphere_sources[lane_key])
    except SearchExhaustedError as exc:
        return {state_key: [], "errors": [build_error_record(f"search_{lane_key}", exc)]}
    return {state_key: sources}


def search_left_pool(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Populate the left-leaning source pool."""
    return _search_lane_pool(state, config, "left", "left_sources")


def search_center_pool(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Populate the centrist source pool."""
    return _search_lane_pool(
        state,
        config,
        "centrist",
        "centrist_sources",
    )


def search_right_pool(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Populate the right-leaning source pool."""
    return _search_lane_pool(state, config, "right", "right_sources")


def search_people_pool(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Populate the people-perspective source pool."""
    return _search_lane_pool(
        state,
        config,
        "people",
        "people_sources",
    )
