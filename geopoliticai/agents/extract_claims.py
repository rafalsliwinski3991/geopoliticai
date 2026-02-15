from __future__ import annotations

from geopoliticai.governance import extract_claims
from geopoliticai.models import PipelineState


def extract_claims_agent(state: PipelineState) -> PipelineState:
    return extract_claims(state)
