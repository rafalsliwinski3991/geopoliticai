"""Claim generation helpers."""

from __future__ import annotations

import logging
from typing import List

from pydantic import BaseModel, Field

from geopoliticai.config import ENGLISH_INFOSPHERE_SOURCES
from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import Claim, PipelineState, Source

logger = logging.getLogger(__name__)


class ClaimItem(BaseModel):
    text: str = ""
    source_ids: List[str] = Field(default_factory=list)


class ClaimsOutput(BaseModel):
    claims: List[ClaimItem] = Field(default_factory=list)


def build_claims(
    state: PipelineState,
    lens: str,
    sources: List[Source],
    references: List[tuple[str, str]] | None = None,
    language: str | None = None,
) -> List[Claim]:
    logger.info("Building claims: lens=%s sources=%d", lens, len(sources))
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in sources
    )
    if references is None:
        if lens == "leftist":
            reference_sources_list = ENGLISH_INFOSPHERE_SOURCES["left"]
        elif lens == "centrist":
            reference_sources_list = ENGLISH_INFOSPHERE_SOURCES["centrist"]
        else:
            reference_sources_list = ENGLISH_INFOSPHERE_SOURCES["right"]
    else:
        reference_sources_list = references
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in reference_sources_list
    )
    response_language = "Polish" if language == "polish" else "English"

    output = invoke_structured_chain(
        schema=ClaimsOutput,
        system_prompt="You are a political analyst who writes precise, source-grounded claims.",
        human_prompt=(
            "Query: {query}\n"
            "Response language: {response_language}\n\n"
            "Sources:\n{source_block}\n\n"
            "Preferred references (use for framing; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Provide 3-5 analytically cautious claims from the perspective: {lens}.\n"
            "- Use only the sources provided.\n"
            "- Each claim must cite one or more source IDs."
        ),
        variables={
            "query": state["query"],
            "response_language": response_language,
            "source_block": source_block,
            "reference_block": reference_block,
            "lens": lens,
        },
        temperature=0.2,
    )

    claims = []
    for item in output.claims:
        text = item.text.strip()
        source_ids = [sid for sid in item.source_ids if isinstance(sid, str)]
        if text:
            claims.append(Claim(text=text, source_ids=source_ids))
    return claims


def leftist_expert(state: PipelineState) -> PipelineState:
    return {
        **state,
        "left_claims": build_claims(state, "leftist", state["left_sources"]),
    }


def centrist_expert(state: PipelineState) -> PipelineState:
    return {
        **state,
        "centrist_claims": build_claims(state, "centrist", state["centrist_sources"]),
    }


def right_expert(state: PipelineState) -> PipelineState:
    return {
        **state,
        "right_claims": build_claims(state, "right-wing", state["right_sources"]),
    }
