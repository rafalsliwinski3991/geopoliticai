"""Web search utilities."""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Union

from tavily import TavilyClient

from geopoliticai.models import PipelineState, Source

logger = logging.getLogger(__name__)


def _seed_for_agent(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]], agent_key: str
) -> Optional[List[Source]]:
    if isinstance(seed_sources, list):
        return seed_sources
    if isinstance(seed_sources, dict):
        return seed_sources.get(agent_key)
    return None


def _build_biased_query(query: str, references: List[tuple[str, str]]) -> str:
    sites = [url.replace("https://", "").replace("http://", "") for _, url in references]
    site_filter = " OR ".join(f"site:{site}" for site in sites)
    return f"{query} ({site_filter})"


def web_searcher(
    state: PipelineState,
    agent_key: str,
    references: List[tuple[str, str]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> List[Source]:
    seeded = _seed_for_agent(seed_sources, agent_key)
    if seeded:
        logger.info("Web searcher (%s): using seed_sources (%d)", agent_key, len(seeded))
        return seeded

    tavily_key = os.getenv("TAVILY_KEY")
    if not tavily_key:
        raise ValueError("Missing TAVILY_KEY for live search.")

    logger.info("Web searcher (%s): querying Tavily", agent_key)
    client = TavilyClient(api_key=tavily_key)
    biased_query = _build_biased_query(state["query"], references)
    response = client.search(biased_query, max_results=6, search_depth="advanced")
    sources: List[Source] = []
    for idx, item in enumerate(response.get("results", []), start=1):
        notes = (item.get("content") or "").strip().replace("\n", " ")
        source = Source(
            id=f"S{idx}",
            title=(item.get("title") or "Untitled").strip(),
            url=(item.get("url") or "").strip(),
            notes=notes[:240] if notes else "No summary provided.",
        )
        sources.append(source)
        logger.info(
            "Web searcher (%s): source=%s url=%s", agent_key, source.title, source.url
        )

    logger.info("Web searcher (%s): received %d sources", agent_key, len(sources))
    return sources
