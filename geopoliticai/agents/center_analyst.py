"""Centrist analyst agent for generating claims from sources."""

from __future__ import annotations

from geopoliticai.agents.generic_analyst import generic_analyst_agent
from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import PipelineState


def center_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    """Generate centrist claims grounded in the provided sources."""
    return generic_analyst_agent(
        state,
        infosphere_sources,
        language,
        lane_key="centrist",
        ideology="centrist",
        model_key="center_analyst",
        log_label="Centrist",
        perspective_label="Centrist",
        fallback_limit=2,
        invoke_chain=invoke_structured_chain,
    )
