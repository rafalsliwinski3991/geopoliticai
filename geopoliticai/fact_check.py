"""Fact-checking stage for the pipeline."""

from __future__ import annotations

import logging
from typing import List, Literal

from pydantic import BaseModel, Field

from geopoliticai.config import ENGLISH_INFOSPHERE_SOURCES
from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import Claim, FactCheckResult, PipelineState

logger = logging.getLogger(__name__)


class FactCheckItem(BaseModel):
    claim_text: str = ""
    verdict: Literal["TRUE", "PARTIALLY TRUE", "MISLEADING", "FALSE"] | str = ""
    rationale: str = ""
    source_ids: List[str] = Field(default_factory=list)


class FactCheckOutput(BaseModel):
    results: List[FactCheckItem] = Field(default_factory=list)


def fact_checker(
    state: PipelineState,
    references: List[tuple[str, str]] | None = None,
    language: str | None = None,
) -> PipelineState:
    logger.info(
        "Fact checking: claims=%d",
        len(state["left_claims"]) + len(state["centrist_claims"]) + len(state["right_claims"]),
    )
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in state["fact_sources"]
    )
    claims = state["left_claims"] + state["centrist_claims"] + state["right_claims"]
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in claims
    )
    if references is None:
        reference_sources_list = ENGLISH_INFOSPHERE_SOURCES["fact"]
    else:
        reference_sources_list = references
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in reference_sources_list
    )
    response_language = "Polish" if language == "polish" else "English"

    data = invoke_structured_chain(
        schema=FactCheckOutput,
        system_prompt="You are a meticulous fact-checker who only uses the provided sources.",
        human_prompt=(
            "Sources:\n{source_block}\n\n"
            "Claims:\n{claims_block}\n\n"
            "Preferred fact-check references (use for methods; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Fact-check each claim against the sources. "
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

    return {**state, "fact_checks": results}
