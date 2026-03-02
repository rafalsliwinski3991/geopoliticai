from __future__ import annotations

from geopoliticai.models import PipelineState
from geopoliticai.planning import build_research_plan


def build_research_plan_step(state: PipelineState) -> PipelineState:
    return build_research_plan(state)
