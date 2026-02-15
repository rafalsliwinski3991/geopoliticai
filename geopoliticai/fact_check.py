"""Backward-compatible fact-check helper delegating to agent modules."""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from geopoliticai.agents.cross_check_facts import cross_check_facts_agent
from geopoliticai.models import PipelineState, Source


def fact_checker(
    state: PipelineState,
    references: List[tuple[str, str]] | None = None,
    language: str | None = None,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    infosphere_sources = {"fact": references or []}
    return cross_check_facts_agent(
        state,
        infosphere_sources=infosphere_sources,
        language=language or state.get("language", "english"),
        seed_sources=seed_sources,
    )
