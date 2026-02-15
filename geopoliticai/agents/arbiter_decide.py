from __future__ import annotations

from geopoliticai.governance import arbiter_decide
from geopoliticai.models import PipelineState


def arbiter_decide_agent(state: PipelineState) -> PipelineState:
    return arbiter_decide(state)
