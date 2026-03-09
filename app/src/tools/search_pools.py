"""Search pool helpers for populating lane-specific source lists."""

from __future__ import annotations

from models import PipelineState
from search import web_searcher


def _search_lane_pool(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    lane_key: str,
    state_key: str,
) -> PipelineState:
    """Populate a single lane's sources via the web searcher."""
    return {
        state_key: web_searcher(state, lane_key, infosphere_sources[lane_key]),
    }


def search_left_pool(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
) -> PipelineState:
    """Populate the left-leaning source pool."""
    return _search_lane_pool(state, infosphere_sources, "left", "left_sources")


def search_center_pool(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
) -> PipelineState:
    """Populate the centrist source pool."""
    return _search_lane_pool(
        state,
        infosphere_sources,
        "centrist",
        "centrist_sources",
    )


def search_right_pool(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
) -> PipelineState:
    """Populate the right-leaning source pool."""
    return _search_lane_pool(state, infosphere_sources, "right", "right_sources")


def search_people_pool(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
) -> PipelineState:
    """Populate the people-perspective source pool."""
    return _search_lane_pool(
        state,
        infosphere_sources,
        "people",
        "people_sources",
    )
