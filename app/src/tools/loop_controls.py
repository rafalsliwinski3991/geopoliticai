from __future__ import annotations

from models import PipelineState


def perform_verification_loop(state: PipelineState) -> PipelineState:
    # Minimal implementation: record loop and clear pending verifications for next pass.
    return {
        **state,
        "loop_count": state["loop_count"] + 1,
        "verification_to_do": [],
    }


def perform_revision_loop(state: PipelineState) -> PipelineState:
    # Minimal implementation: record loop and clear pending rewrites for next pass.
    return {
        **state,
        "loop_count": state["loop_count"] + 1,
        "rewrites_to_do": [],
    }
