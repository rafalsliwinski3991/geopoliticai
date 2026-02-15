from __future__ import annotations

from typing import Dict, List, Optional, Union

from geopoliticai.models import PipelineState, Source
from geopoliticai.search import web_searcher


def _search_lane_pool(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    lane_key: str,
    state_key: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return {
        **state,
        state_key: web_searcher(state, lane_key, infosphere_sources[lane_key], seed_sources),
    }


def search_left_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return _search_lane_pool(state, infosphere_sources, "left", "left_sources", seed_sources)


def search_center_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return _search_lane_pool(
        state,
        infosphere_sources,
        "centrist",
        "centrist_sources",
        seed_sources,
    )


def search_right_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return _search_lane_pool(state, infosphere_sources, "right", "right_sources", seed_sources)
