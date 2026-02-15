from __future__ import annotations

from typing import Dict, List, Optional, Union

from geopoliticai.fact_check import fact_checker
from geopoliticai.models import PipelineState, Source
from geopoliticai.search import web_searcher


def cross_check_facts_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    with_fact_sources = {
        **state,
        "fact_sources": web_searcher(state, "fact", infosphere_sources["fact"], seed_sources),
    }
    return fact_checker(with_fact_sources, infosphere_sources["fact"], language)
