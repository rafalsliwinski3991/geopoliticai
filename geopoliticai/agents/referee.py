from __future__ import annotations

from geopoliticai.governance import referee
from geopoliticai.models import PipelineState


def referee_agent(state: PipelineState) -> PipelineState:
    return referee(state)
