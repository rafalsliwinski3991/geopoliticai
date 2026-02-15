"""Backward-compatible governance helpers delegating to agent modules."""

from __future__ import annotations

from geopoliticai.tools.arbiter_decide import decide_arbiter_outcome, route_from_arbiter_decision
from geopoliticai.tools.extract_claims import extract_claims_for_verification
from geopoliticai.tools.referee import run_referee_checks
from geopoliticai.tools.loop_controls import perform_revision_loop, perform_verification_loop
from geopoliticai.models import PipelineState


def referee(state: PipelineState) -> PipelineState:
    return run_referee_checks(state)


def extract_claims(state: PipelineState) -> PipelineState:
    return extract_claims_for_verification(state)


def arbiter_decide(state: PipelineState) -> PipelineState:
    return decide_arbiter_outcome(state)


def verify_more(state: PipelineState) -> PipelineState:
    return perform_verification_loop(state)


def revise_analyses(state: PipelineState) -> PipelineState:
    return perform_revision_loop(state)
