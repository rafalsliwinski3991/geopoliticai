from __future__ import annotations

from typing import Dict, List, Optional, Union

from geopoliticai.models import PipelineState, Source
from geopoliticai.search import web_searcher


def search_left_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return {
        **state,
        "left_sources": web_searcher(state, "left", infosphere_sources["left"], seed_sources),
    }
