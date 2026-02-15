from __future__ import annotations

from geopoliticai.models import PipelineState


def extract_claims_agent(state: PipelineState) -> PipelineState:
    extracted = []
    for lane, claims in (
        ("left", state["left_claims"]),
        ("centrist", state["centrist_claims"]),
        ("right", state["right_claims"]),
    ):
        for claim in claims:
            extracted.append(
                {
                    "text": claim.text,
                    "stmt_type": "INTERPRETATION",
                    "asserted_by": [lane],
                    "citations": claim.source_ids,
                    "confidence": 0.65,
                }
            )
    return {**state, "extracted_claims": extracted}
