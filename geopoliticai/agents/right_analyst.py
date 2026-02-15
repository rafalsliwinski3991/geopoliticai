"""Right-leaning analyst agent for generating claims from sources."""

from __future__ import annotations

import logging
from typing import Any, List

from pydantic import BaseModel, Field, field_validator

from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import Claim, PipelineState, Source

logger = logging.getLogger(__name__)


class RightClaimItem(BaseModel):
    """Single right-leaning claim with source identifiers."""

    text: str = ""
    source_ids: List[str] = Field(default_factory=list)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _coerce_source_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]


class RightClaimsOutput(BaseModel):
    """Structured output for right analyst claims."""

    claims: List[RightClaimItem] = Field(default_factory=list)


def _extract_claims(items: List[RightClaimItem]) -> List[Claim]:
    """Convert model claim items into validated Claim objects."""
    return [
        Claim(text=item.text.strip(), source_ids=[sid for sid in item.source_ids if isinstance(sid, str)])
        for item in items
        if item.text.strip()
    ]


def _fallback_claims_from_sources(sources: List[Source], limit: int = 2) -> List[Claim]:
    """Build minimal claims directly from source notes when the LLM returns none."""
    claims: List[Claim] = []
    for src in sources[:limit]:
        snippet = (src.notes or src.title or "").strip()
        if not snippet:
            continue
        text = f"{src.title}: {snippet}"
        claims.append(Claim(text=text, source_ids=[src.id]))
    return claims


def right_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    """Generate right-leaning claims grounded in the provided sources."""
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in state["right_sources"]
    )
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in infosphere_sources["right"]
    )
    response_language = "Polish" if language == "polish" else "English"

    output = invoke_structured_chain(
        schema=RightClaimsOutput,
        system_prompt="You are a political analyst who writes precise, source-grounded claims.",
        human_prompt=(
            "Query: {query}\n"
            "Response language: {response_language}\n\n"
            "Sources:\n{source_block}\n\n"
            "Preferred references (use for framing; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Provide exactly 1 analytically cautious claim from the perspective: right-wing.\n"
            "- Use only the sources provided.\n"
            "- The claim must cite one or more source IDs.\n"
            "- If sources are general, produce one factual claim grounded in them.\n"
            "- Never return an empty list; return exactly one claim."
        ),
        variables={
            "query": state["query"],
            "response_language": response_language,
            "source_block": source_block,
            "reference_block": reference_block,
        },
        temperature=0.2,
    )
    claims = _extract_claims(output.claims)[:1]
    if not claims:
        logger.warning(
            "Right analyst produced 0 claims from %d sources.", len(state["right_sources"])
        )
        retry = invoke_structured_chain(
            schema=RightClaimsOutput,
            system_prompt="You are a political analyst who writes precise, source-grounded claims.",
            human_prompt=(
                "Query: {query}\n"
                "Response language: {response_language}\n\n"
                "Sources:\n{source_block}\n\n"
                "Task: Provide exactly 1 factual claim from the sources. "
                "If the sources are descriptive, turn them into one concise claim. "
                "The claim must cite one or more source IDs. "
                "Never return an empty list."
            ),
            variables={
                "query": state["query"],
                "response_language": response_language,
                "source_block": source_block,
            },
            temperature=0.1,
        )
        claims = _extract_claims(retry.claims)[:1]
        if not claims:
            claims = _fallback_claims_from_sources(state["right_sources"], limit=2)
        if not claims:
            logger.warning("Right analyst fallback empty; creating minimal claim from query.")
            claims = [Claim(text=f"Right perspective on: {state['query']}", source_ids=[])]
    else:
        logger.info("Right analyst produced %d claims.", len(claims))
        for idx, claim in enumerate(claims[:5], start=1):
            sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
            logger.info("Right claim %d: %s (Sources: %s)", idx, claim.text, sources)
    return {**state, "right_claims": claims}
