from __future__ import annotations

from geopoliticai.claims import build_claims
from geopoliticai.models import PipelineState


def right_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return {
        **state,
        "right_claims": build_claims(
            state,
            "right-wing",
            state["right_sources"],
            infosphere_sources["right"],
            language,
        ),
    }
