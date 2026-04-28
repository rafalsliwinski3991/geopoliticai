"""Right-leaning analyst agent for generating claims from sources."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from llm import invoke_structured_chain
from models import PipelineState
from nodes.generic_analyst import generic_analyst_agent
from nodes.runtime_config import runtime_infosphere_sources, runtime_language


def right_analyst_agent(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Generate right-leaning claims grounded in the provided sources."""
    return generic_analyst_agent(
        state,
        runtime_infosphere_sources(state, config),
        runtime_language(state, config),
        lane_key="right",
        ideology="right-wing",
        model_key="right_analyst",
        log_label="Right",
        perspective_label="Right",
        fallback_limit=2,
        invoke_chain=invoke_structured_chain,
    )
