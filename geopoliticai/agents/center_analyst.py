from __future__ import annotations

from geopoliticai.claims import build_claims
from geopoliticai.models import PipelineState


def center_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return {
        **state,
        "centrist_claims": build_claims(
            state,
            "centrist",
            state["centrist_sources"],
            infosphere_sources["centrist"],
            language,
        ),
    }
