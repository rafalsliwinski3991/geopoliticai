from __future__ import annotations

from geopoliticai.governance import verify_more
from geopoliticai.models import PipelineState


def verify_more_agent(state: PipelineState) -> PipelineState:
    return verify_more(state)
