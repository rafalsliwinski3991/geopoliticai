"""Fact-checking agent for verifying claims against sources."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from geopoliticai.config import get_model
from geopoliticai.models import Claim, FactCheckResult, PipelineState, Source
from geopoliticai.search import web_searcher
from geopoliticai.llm import invoke_structured_chain

logger = logging.getLogger(__name__)


class FactCheckItem(BaseModel):
    """Single fact-check result for a claim."""

    claim_text: str = ""
    verdict: Literal["TRUE", "PARTIALLY TRUE", "MISLEADING", "FALSE"] | str = ""
    rationale: str = ""
    source_ids: List[str] = Field(default_factory=list)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _coerce_source_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]


class FactCheckOutput(BaseModel):
    """Structured output for a batch of fact-check results."""

    results: List[FactCheckItem] = Field(default_factory=list)


def cross_check_facts_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    """Run fact checks for all claims and return structured verdicts."""
    with_fact_sources = {
        **state,
        "fact_sources": web_searcher(state, "fact", infosphere_sources["fact"], seed_sources),
    }

    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in with_fact_sources["fact_sources"]
    )
    claims = (
        with_fact_sources["left_claims"]
        + with_fact_sources["centrist_claims"]
        + with_fact_sources["right_claims"]
        + with_fact_sources["people_claims"]
    )
    logger.info(
        "Fact-check: sources=%d claims=%d",
        len(with_fact_sources["fact_sources"]),
        len(claims),
    )
    for idx, claim in enumerate(claims, start=1):
        sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
        logger.info(
            "Fact-check input claim %d/%d: %s (Sources: %s)",
            idx,
            len(claims),
            claim.text,
            sources,
        )
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in claims
    )
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in infosphere_sources["fact"]
    )
    response_language = "Polish" if language == "polish" else "English"
    model_name = get_model("cross_check_facts")

    data = invoke_structured_chain(
        schema=FactCheckOutput,
        system_prompt="You are a meticulous fact-checker who only uses the provided sources.",
        human_prompt=(
            "Sources:\n{source_block}\n\n"
            "Claims:\n{claims_block}\n\n"
            "Preferred fact-check references (use for methods; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Fact-check each claim strictly against the provided sources. "
            "Do not speculate or add outside knowledge. "
            "Use verdicts: TRUE, PARTIALLY TRUE, MISLEADING, FALSE. "
            "Write the rationale in {response_language}. Keep the verdict labels exactly as specified."
        ),
        variables={
            "source_block": source_block,
            "claims_block": claims_block,
            "reference_block": reference_block,
            "response_language": response_language,
        },
        temperature=0.0,
        model=model_name,
    )

    results: List[FactCheckResult] = []
    for item in data.results:
        claim_text = item.claim_text.strip()
        verdict = item.verdict.strip()
        rationale = item.rationale.strip()
        source_ids = [sid for sid in item.source_ids if isinstance(sid, str)]
        if claim_text and verdict:
            results.append(
                FactCheckResult(
                    claim=Claim(text=claim_text, source_ids=source_ids),
                    verdict=verdict,
                    rationale=rationale,
                )
            )
    logger.info("Fact-check: produced %d verdicts", len(results))
    for idx, res in enumerate(results, start=1):
        sources = ", ".join(res.claim.source_ids) if res.claim.source_ids else "none"
        logger.info(
            "Fact-check %d/%d: %s — %s (Sources: %s)",
            idx,
            len(results),
            res.verdict,
            res.claim.text,
            sources,
        )
    return {**with_fact_sources, "fact_checks": results}
