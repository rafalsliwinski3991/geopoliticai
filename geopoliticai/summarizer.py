"""Backward-compatible summarizer helper delegating to agent modules."""

from __future__ import annotations

from geopoliticai.agents.compose_final import compose_final_agent
from geopoliticai.models import PipelineState


def summarizer_judge(state: PipelineState, language: str | None = None) -> PipelineState:
    return compose_final_agent(state, language or state.get("language", "english"))
