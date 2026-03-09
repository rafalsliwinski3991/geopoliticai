"""People-perspective analyst agent for generating claims from sources."""

from __future__ import annotations

from agents.generic_analyst import generic_analyst_agent
from llm import invoke_structured_chain
from models import PipelineState


def people_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    """Generate people-perspective claims grounded in the provided sources."""
    return generic_analyst_agent(
        state,
        infosphere_sources,
        language,
        lane_key="people",
        ideology="people",
        model_key="people_analyst",
        log_label="People",
        perspective_label="People",
        fallback_limit=3,
        invoke_chain=invoke_structured_chain,
    )
