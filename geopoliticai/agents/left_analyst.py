from __future__ import annotations

from geopoliticai.claims import build_claims
from geopoliticai.models import PipelineState


def left_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return {
        **state,
        "left_claims": build_claims(
            state,
            "leftist",
            state["left_sources"],
            infosphere_sources["left"],
            language,
        ),
    }
