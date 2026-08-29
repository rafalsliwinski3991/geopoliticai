"""Retrieval node: allow-listed search, fetch, and extraction."""

from __future__ import annotations

import logging
from typing import Any

from agents.expert.config import RETRIEVAL
from agents.expert.consts.sources import EXPERT_SOURCES
from agents.expert.state import PipelineState
from models import NoSourcesError
from search import fetch_sources, search_allowlisted

logger = logging.getLogger(__name__)


async def search_and_fetch(state: PipelineState) -> dict[str, Any]:
    """Search the allow-list, fetch top pages, and extract article text."""
    candidates = (await search_allowlisted(state["query"], EXPERT_SOURCES))[
        : RETRIEVAL.fetch_candidates
    ]
    if not candidates:
        raise NoSourcesError(
            "No approved sources were found for this query. Try rephrasing it."
        )
    sources = (await fetch_sources(candidates, EXPERT_SOURCES))[
        : RETRIEVAL.keep_sources
    ]
    if not sources:
        raise NoSourcesError(
            "None of the approved sources for this query could be fetched or extracted."
        )
    logger.info(
        "search_and_fetch: %d candidates -> %d sources", len(candidates), len(sources)
    )
    return {"sources": sources}
