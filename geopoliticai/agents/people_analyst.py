"""People-perspective analyst agent for generating claims from sources."""

from __future__ import annotations

import logging
from typing import Any, List

from pydantic import BaseModel, Field, field_validator

from geopoliticai.config import get_model
from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import Claim, PipelineState, Source

logger = logging.getLogger(__name__)


class PeopleClaimItem(BaseModel):
    """Single people-perspective claim with source identifiers."""

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


class PeopleClaimsOutput(BaseModel):
    """Structured output for people analyst claims."""

    claims: List[PeopleClaimItem] = Field(default_factory=list)


def _extract_claims(items: List[PeopleClaimItem]) -> List[Claim]:
    """Convert model claim items into validated Claim objects."""
    return [
        Claim(text=item.text.strip(), source_ids=[sid for sid in item.source_ids if isinstance(sid, str)])
        for item in items
        if item.text.strip()
    ]


def _fallback_claims_from_sources(sources: List[Source], limit: int = 3) -> List[Claim]:
    """Build minimal claims directly from source notes when the LLM returns none."""
    claims: List[Claim] = []
    for src in sources[:limit]:
        snippet = (src.notes or src.title or "").strip()
        if not snippet:
            continue
        text = f"{src.title}: {snippet}"
        claims.append(Claim(text=text, source_ids=[src.id]))
    return claims


def people_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    """Generate people-perspective claims grounded in the provided sources."""
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in state["people_sources"]
    )
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in infosphere_sources["people"]
    )
    response_language = "Polish" if language == "polish" else "English"
    model_name = get_model("people_analyst")

    output = invoke_structured_chain(
        schema=PeopleClaimsOutput,
        system_prompt="You are a political analyst who writes precise, source-grounded claims.",
        human_prompt=(
            "Query: {query}\n"
            "Response language: {response_language}\n\n"
            "Sources:\n{source_block}\n\n"
            "Preferred references (use for framing; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Provide 3-5 analytically cautious claims from the perspective: people.\n"
            "- Use only the sources provided.\n"
            "- Each claim must cite one or more source IDs.\n"
            "Return a JSON object with key `claims`."
        ),
        variables={
            "query": state["query"],
            "response_language": response_language,
            "source_block": source_block,
            "reference_block": reference_block,
        },
        temperature=0.2,
        model=model_name,
    )
    claims = _extract_claims(output.claims)
    if not claims:
        logger.info(
            "People analyst: initial pass produced 0 claims from %d sources; retrying.",
            len(state["people_sources"]),
        )
        retry = invoke_structured_chain(
            schema=PeopleClaimsOutput,
            system_prompt="You are a political analyst who writes precise, source-grounded claims.",
            human_prompt=(
                "Query: {query}\n"
                "Response language: {response_language}\n\n"
                "Sources:\n{source_block}\n\n"
                "Task: Provide 2-3 factual claims from the sources. "
                "Each claim must cite one or more source IDs. "
                "Never return an empty list."
            ),
            variables={
                "query": state["query"],
                "response_language": response_language,
                "source_block": source_block,
            },
            temperature=0.1,
            model=model_name,
        )
        claims = _extract_claims(retry.claims)
        if not claims:
            logger.info("People analyst: retry returned 0 claims; using source-note fallback.")
            claims = _fallback_claims_from_sources(state["people_sources"], limit=3)
        if not claims:
            logger.warning("People analyst fallback empty; creating minimal claim from query.")
            claims = [Claim(text=f"People perspective on: {state['query']}", source_ids=[])]
    logger.info("People analyst: produced %d claims.", len(claims))
    for idx, claim in enumerate(claims, start=1):
        sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
        logger.info(
            "People claim %d/%d: %s (Sources: %s)",
            idx,
            len(claims),
            claim.text,
            sources,
        )
    return {**state, "people_claims": claims}
