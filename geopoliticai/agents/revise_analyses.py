from __future__ import annotations

from geopoliticai.models import PipelineState


def revise_analyses_agent(state: PipelineState) -> PipelineState:
    # Minimal implementation: record loop and clear pending rewrites for next pass.
    return {
        **state,
        "loop_count": state["loop_count"] + 1,
        "rewrites_to_do": [],
    }
