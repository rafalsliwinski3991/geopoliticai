"""Backward-compatible governance helpers delegating to agent modules."""

from __future__ import annotations

from geopoliticai.agents.arbiter_decide import arbiter_decide_agent, route_from_arbiter
from geopoliticai.agents.extract_claims import extract_claims_agent
from geopoliticai.agents.referee import referee_agent
from geopoliticai.agents.revise_analyses import revise_analyses_agent
from geopoliticai.agents.verify_more import verify_more_agent
from geopoliticai.models import PipelineState


def referee(state: PipelineState) -> PipelineState:
    return referee_agent(state)


def extract_claims(state: PipelineState) -> PipelineState:
    return extract_claims_agent(state)


def arbiter_decide(state: PipelineState) -> PipelineState:
    return arbiter_decide_agent(state)


def verify_more(state: PipelineState) -> PipelineState:
    return verify_more_agent(state)


def revise_analyses(state: PipelineState) -> PipelineState:
    return revise_analyses_agent(state)
