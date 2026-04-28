"""Claim extraction node for downstream verification."""

from __future__ import annotations

from typing import Any

from models import PipelineState


def extract_claims_for_verification(state: PipelineState) -> dict[str, Any]:
    """Flatten analyst claims into verification records."""
    extracted = []
    for lane, claims in (
        ("left", state["left_claims"]),
        ("centrist", state["centrist_claims"]),
        ("right", state["right_claims"]),
        ("people", state["people_claims"]),
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
    return {"extracted_claims": extracted}
