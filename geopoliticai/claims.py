"""Backward-compatible claim helpers delegating to agent modules."""

from __future__ import annotations

from geopoliticai.agents.center_analyst import center_analyst_agent
from geopoliticai.agents.left_analyst import left_analyst_agent
from geopoliticai.agents.right_analyst import right_analyst_agent
from geopoliticai.models import PipelineState


def leftist_expert(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return left_analyst_agent(state, infosphere_sources, language)


def centrist_expert(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return center_analyst_agent(state, infosphere_sources, language)


def right_expert(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return right_analyst_agent(state, infosphere_sources, language)
