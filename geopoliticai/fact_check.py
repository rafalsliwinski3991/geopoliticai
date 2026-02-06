"""Fact-checking stage for the pipeline."""

from __future__ import annotations

import logging
from typing import List

from geopoliticai.config import FACT_CHECK_SOURCES
from geopoliticai.llm import llm_json
from geopoliticai.models import Claim, FactCheckResult, PipelineState

logger = logging.getLogger(__name__)


def fact_checker(state: PipelineState) -> PipelineState:
    logger.info(
        "Fact checking: claims=%d",
        len(state["left_claims"])
        + len(state["centrist_claims"])
        + len(state["right_claims"]),
    )
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in state["fact_sources"]
    )
    claims = state["left_claims"] + state["centrist_claims"] + state["right_claims"]
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in claims
    )
    reference_block = "\n".join(f"- {name} ({url})" for name, url in FACT_CHECK_SOURCES)
    user = f"""
Sources:
{source_block}

Claims:
{claims_block}

Preferred fact-check references (use for methods; do not invent citations):
{reference_block}

Task: Fact-check each claim against the sources. Use verdicts: TRUE, PARTIALLY TRUE, MISLEADING, FALSE.
Return JSON: {{"results": [{{"claim_text": "...", "verdict": "...", "rationale": "...", "source_ids": ["S1"]}}]}}.
""".strip()

    data = llm_json(
        system="You are a meticulous fact-checker who only uses the provided sources.",
        user=user,
    )

    results: List[FactCheckResult] = []
    for item in data.get("results", []):
        claim_text = (item.get("claim_text") or "").strip()
        verdict = (item.get("verdict") or "").strip()
        rationale = (item.get("rationale") or "").strip()
        source_ids = [sid for sid in item.get("source_ids", []) if isinstance(sid, str)]
        if claim_text and verdict:
            results.append(
                FactCheckResult(
                    claim=Claim(text=claim_text, source_ids=source_ids),
                    verdict=verdict,
                    rationale=rationale,
                )
            )

    return {**state, "fact_checks": results}
