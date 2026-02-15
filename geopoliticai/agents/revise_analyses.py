from __future__ import annotations

from geopoliticai.governance import revise_analyses
from geopoliticai.models import PipelineState


def revise_analyses_agent(state: PipelineState) -> PipelineState:
    return revise_analyses(state)
