from __future__ import annotations

from geopoliticai.models import PipelineState


def verify_more_agent(state: PipelineState) -> PipelineState:
    # Minimal implementation: record loop and clear pending verifications for next pass.
    return {
        **state,
        "loop_count": state["loop_count"] + 1,
        "verification_to_do": [],
    }
