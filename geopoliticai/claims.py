"""Claim generation helpers."""

from __future__ import annotations

import logging
from typing import List

from geopoliticai.config import CENTRIST_SOURCES, LEFTIST_SOURCES, RIGHTIST_SOURCES
from geopoliticai.llm import llm_json
from geopoliticai.models import Claim, PipelineState, Source

logger = logging.getLogger(__name__)


def build_claims(state: PipelineState, lens: str, sources: List[Source]) -> List[Claim]:
    logger.info("Building claims: lens=%s sources=%d", lens, len(sources))
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in sources
    )
    if lens == "leftist":
        reference_sources = LEFTIST_SOURCES
    elif lens == "centrist":
        reference_sources = CENTRIST_SOURCES
    else:
        reference_sources = RIGHTIST_SOURCES
    reference_block = "\n".join(f"- {name} ({url})" for name, url in reference_sources)
    user = f"""
Query: {state['query']}

Sources:
{source_block}

Preferred references (use for framing; do not invent citations):
{reference_block}

Task: Provide 3-5 analytically cautious claims from the perspective: {lens}.
- Use only the sources provided.
- Each claim must cite one or more source IDs.
Return JSON: {{"claims": [{{"text": "...", "source_ids": ["S1", "S2"]}}]}}.
""".strip()

    data = llm_json(
        system="You are a political analyst who writes precise, source-grounded claims.",
        user=user,
    )
    claims = []
    for item in data.get("claims", []):
        text = (item.get("text") or "").strip()
        source_ids = [sid for sid in item.get("source_ids", []) if isinstance(sid, str)]
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
