"""Claim extraction nodes for downstream verification.

Extraction is parallelised across lanes via the LangGraph `Send` API:
`fan_out_extract` dispatches one `extract_claims_lane` worker per lane,
and the `extracted_claims` reducer (`operator.add` on `PipelineState`)
merges their outputs into the converged list.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Send

from geopoliticai.models import Claim, PipelineState

_LANES: tuple[str, ...] = ("left", "centrist", "right", "people")


def _record_for_claim(claim: Claim, lane: str) -> dict[str, Any]:
    return {
        "text": claim.text,
        "stmt_type": "INTERPRETATION",
        "asserted_by": [lane],
        "citations": list(claim.source_ids),
        "confidence": 0.65,
    }


def fan_out_extract(state: PipelineState) -> list[Send]:
    """Dispatch one extraction worker per lane (LangGraph map-reduce)."""
    return [
        Send(
            "extract_claims_lane",
            {"lane": lane, "claims": list(state[f"{lane}_claims"])},
        )
        for lane in _LANES
    ]


def extract_claims_lane(payload: dict[str, Any]) -> dict[str, Any]:
    """Worker: convert one lane's claims into extraction records.

    Returns a partial update merged into `extracted_claims` via the
    `operator.add` reducer declared on `PipelineState`.
    """
    lane = payload["lane"]
    claims = payload.get("claims", [])
    return {"extracted_claims": [_record_for_claim(c, lane) for c in claims]}


def extract_claims_for_verification(state: PipelineState) -> dict[str, Any]:
    """Sequential extraction (kept for tests / non-graph callers)."""
    extracted: list[dict[str, Any]] = []
    for lane in _LANES:
        for claim in state[f"{lane}_claims"]:
            extracted.append(_record_for_claim(claim, lane))
    return {"extracted_claims": extracted}
