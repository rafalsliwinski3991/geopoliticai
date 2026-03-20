from __future__ import annotations

from models import PipelineState
from planning import build_research_plan


def build_research_plan_step(state: PipelineState) -> PipelineState:
    return build_research_plan(state)
