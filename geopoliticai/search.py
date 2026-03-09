"""Web search utilities."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from typing import Dict, List, Optional, Union

from tavily import TavilyClient

from geopoliticai.config import get_analyst_additional_sources, get_model
from geopoliticai.llm import get_openai_client, invoke_openai_json_object
from geopoliticai.models import PipelineState, Source

logger = logging.getLogger(__name__)
MAX_SOURCE_NOTES_CHARS = 400
LANE_SOURCE_PREFIXES = {
    "left": "L",
    "centrist": "C",
    "right": "R",
    "people": "P",
    "fact": "F",
}


def _source_id_for_lane(agent_key: str, index: int) -> str:
    """Build a lane-prefixed source ID."""
    prefix = LANE_SOURCE_PREFIXES.get(agent_key, "S")
    return f"{prefix}{index}"


def _renumber_lane_sources(agent_key: str, sources: List[Source]) -> List[Source]:
    """Ensure source IDs are lane-prefixed and unique within lane."""
    return [replace(source, id=_source_id_for_lane(agent_key, idx)) for idx, source in enumerate(sources, start=1)]


def _seed_for_agent(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]], agent_key: str
) -> Optional[List[Source]]:
    """Return pre-seeded sources for a given lane if provided."""
    if isinstance(seed_sources, list):
        return seed_sources
    if isinstance(seed_sources, dict):
        return seed_sources.get(agent_key)
    return None


def _build_biased_query(query: str, references: List[tuple[str, str]]) -> str:
    """Build a site-filtered query constrained to preferred references."""
    sites = [url.replace("https://", "").replace("http://", "") for _, url in references]
    site_filter = " OR ".join(f"site:{site}" for site in sites)
    return f"{query} ({site_filter})"


def _normalize_source_notes(raw_notes: str, max_chars: int = MAX_SOURCE_NOTES_CHARS) -> str:
    """Return a compact source summary safe to include in LLM prompts."""
    compact = " ".join((raw_notes or "").split())
    if not compact:
        return "No summary provided."
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _select_sources_with_llm(
    *,
    agent_key: str,
    query: str,
    candidates: List[Source],
    count: int,
) -> List[Source]:
    """Use the LLM to pick ideologically aligned sources from candidates."""
    if not candidates or count <= 0:
        return []

    client = get_openai_client()
    model = get_model(agent_key)
    catalog = [
        {
            "id": idx,
            "title": src.title,
            "url": src.url,
            "notes": src.notes,
        }
        for idx, src in enumerate(candidates, start=1)
    ]
    system_prompt = (
        "You select sources based on the analyst's ideology and framing preferences. "
        "Return JSON only."
    )
    user_prompt = (
        "Task: Pick the best sources for the analyst lane.\n"
        f"Lane: {agent_key}\n"
        f"Query: {query}\n"
        f"Pick exactly {count} sources from the catalog.\n"
        "Return a JSON object: {\"selected_ids\": [int, ...]}.\n"
        f"Catalog: {json.dumps(catalog, ensure_ascii=False)}"
    )
    try:
        payload = invoke_openai_json_object(
            client=client,
            model=model,
            system_content=system_prompt + " Output must be JSON.",
            user_content=user_prompt,
            temperature=0.2,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.exception("LLM source selection returned invalid payload for lane %s", agent_key)
        return candidates[:count]

    raw_ids = payload.get("selected_ids", [])
    logger.debug(
        "LLM source selector (%s): candidates=%d requested=%d returned_ids=%s",
        agent_key,
        len(candidates),
        count,
        raw_ids,
    )
    selected: List[Source] = []
    for idx in raw_ids:
        try:
            pos = int(idx)
        except (TypeError, ValueError):
            continue
        if 1 <= pos <= len(candidates):
            selected.append(candidates[pos - 1])
    if selected:
        return selected[:count]
    return candidates[:count]


def web_searcher(
    state: PipelineState,
    agent_key: str,
    references: List[tuple[str, str]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    additional_sources: Optional[int] = None,
) -> List[Source]:
    """Run biased search and optionally add extra general sources selected by the LLM."""
    seeded = _seed_for_agent(seed_sources, agent_key)
    if seeded:
        normalized_seeded = _renumber_lane_sources(agent_key, seeded)
        logger.info("Web searcher (%s): using seed_sources (%d)", agent_key, len(normalized_seeded))
        for idx, source in enumerate(normalized_seeded, start=1):
            logger.debug(
                "Web searcher (%s): source %d/%d title=%s url=%s",
                agent_key,
                idx,
                len(normalized_seeded),
                source.title,
                source.url,
            )
        return normalized_seeded

    if additional_sources is None:
        extra_sources = get_analyst_additional_sources()
    else:
        extra_sources = max(additional_sources, 0)
        if additional_sources < 0:
            logger.warning(
                "Web searcher (%s): additional_sources=%d is invalid; using 0.",
                agent_key,
                additional_sources,
            )

    tavily_key = os.getenv("TAVILY_KEY")
    if not tavily_key:
        raise ValueError("Missing TAVILY_KEY for live search.")

    logger.info("Web searcher (%s): querying Tavily", agent_key)
    client = TavilyClient(api_key=tavily_key)
    queries = state.get("research_plan", {}).get("queries") or [state["query"]]
    biased_query = _build_biased_query(queries[0], references)
    logger.debug("Web searcher (%s): built biased query", agent_key)
    response = client.search(biased_query, max_results=3, search_depth="advanced")
    sources: List[Source] = []
    seen_urls: set[str] = set()
    for idx, item in enumerate(response.get("results", []), start=1):
        raw_notes = (item.get("content") or "").strip()
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        source = Source(
            id=_source_id_for_lane(agent_key, idx),
            title=(item.get("title") or "Untitled").strip(),
            url=url,
            notes=_normalize_source_notes(raw_notes),
            content_excerpt=raw_notes or None,
        )
        sources.append(source)
        logger.debug(
            "Web searcher (%s): source=%s url=%s", agent_key, source.title, source.url
        )
        if len(sources) >= 3:
            break

    if extra_sources > 0:
        general_query = queries[0]
        logger.info(
            "Web searcher (%s): querying %d additional sources (general)",
            agent_key,
            extra_sources,
        )
        extra_response = client.search(
            general_query,
            max_results=max(extra_sources * 3, extra_sources),
            search_depth="advanced",
        )
        extra_candidates: List[Source] = []
        for item in extra_response.get("results", []):
            raw_notes = (item.get("content") or "").strip()
            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            source = Source(
                id=_source_id_for_lane(agent_key, len(sources) + len(extra_candidates) + 1),
                title=(item.get("title") or "Untitled").strip(),
                url=url,
                notes=_normalize_source_notes(raw_notes),
                content_excerpt=raw_notes or None,
            )
            extra_candidates.append(source)
        logger.info("Web searcher (%s): gathered %d extra candidates", agent_key, len(extra_candidates))

        selected_extras = _select_sources_with_llm(
            agent_key=agent_key,
            query=general_query,
            candidates=extra_candidates,
            count=extra_sources,
        )
        logger.info(
            "Web searcher (%s): LLM selected %d extras (requested %d)",
            agent_key,
            len(selected_extras),
            extra_sources,
        )
        for source in selected_extras:
            sources.append(source)
            logger.debug(
                "Web searcher (%s): extra source=%s url=%s",
                agent_key,
                source.title,
                source.url,
            )
            if len(sources) >= 3 + extra_sources:
                break

    sources = _renumber_lane_sources(agent_key, sources)

    logger.info("Web searcher (%s): selected %d sources", agent_key, len(sources))
    for idx, source in enumerate(sources, start=1):
        logger.debug(
            "Web searcher (%s): source %d/%d title=%s url=%s",
            agent_key,
            idx,
            len(sources),
            source.title,
            source.url,
        )
    return sources
