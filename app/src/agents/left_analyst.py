"""Left-leaning analyst agent for generating claims from sources."""

from __future__ import annotations

from agents.generic_analyst import generic_analyst_agent
from llm import invoke_structured_chain
from models import PipelineState


def left_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    """Generate left-leaning claims grounded in the provided sources."""
    return generic_analyst_agent(
        state,
        infosphere_sources,
        language,
        lane_key="left",
        ideology="leftist",
        model_key="left_analyst",
        log_label="Left",
        perspective_label="Left",
        fallback_limit=2,
        invoke_chain=invoke_structured_chain,
    )
