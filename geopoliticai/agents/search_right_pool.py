from __future__ import annotations

from typing import Dict, List, Optional, Union

from geopoliticai.models import PipelineState, Source
from geopoliticai.search import web_searcher


def search_right_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return {
        **state,
        "right_sources": web_searcher(state, "right", infosphere_sources["right"], seed_sources),
    }
