"""People-perspective analyst agent for generating claims from sources."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from llm import invoke_structured_chain
from models import PipelineState
from nodes.generic_analyst import generic_analyst_agent
from nodes.runtime_config import runtime_infosphere_sources, runtime_language


def people_analyst_agent(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Generate people-perspective claims grounded in the provided sources."""
    return generic_analyst_agent(
        state,
        runtime_infosphere_sources(state, config),
        runtime_language(state, config),
        lane_key="people",
        ideology="people",
        model_key="people_analyst",
        log_label="People",
        perspective_label="People",
        fallback_limit=3,
        invoke_chain=invoke_structured_chain,
    )
