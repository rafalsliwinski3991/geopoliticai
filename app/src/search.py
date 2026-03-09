"""Web search utilities."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import List
from urllib.parse import urlparse

from tavily import TavilyClient

from models import PipelineState, Source

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


def _build_biased_query(query: str, references: List[tuple[str, str]]) -> str:
    """Build a site-filtered query constrained to preferred references."""
    sites = sorted(_allowed_reference_domains(references))
    if not sites:
        return query
    site_filter = " OR ".join(f"site:{site}" for site in sites)
    return f"{query} ({site_filter})"


def _extract_domain(url: str) -> str:
    """Return normalized domain for a URL-like string."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path.split("/")[0]).lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _allowed_reference_domains(references: List[tuple[str, str]]) -> set[str]:
    """Return normalized set of domains allowed for the lane."""
    domains: set[str] = set()
    for _, ref_url in references:
        domain = _extract_domain(ref_url)
        if domain:
            domains.add(domain)
    return domains


def _url_matches_allowed_domains(url: str, allowed_domains: set[str]) -> bool:
    """Return whether a candidate URL is in the configured lane domains."""
    if not allowed_domains:
        return False
    domain = _extract_domain(url)
    if not domain:
        return False
    return any(
        domain == allowed_domain or domain.endswith(f".{allowed_domain}")
        for allowed_domain in allowed_domains
    )


def _normalize_source_notes(raw_notes: str, max_chars: int = MAX_SOURCE_NOTES_CHARS) -> str:
    """Return a compact source summary safe to include in LLM prompts."""
    compact = " ".join((raw_notes or "").split())
    if not compact:
        return "No summary provided."
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def web_searcher(
    state: PipelineState,
    agent_key: str,
    references: List[tuple[str, str]],
) -> List[Source]:
    """Search Tavily only within the lane's configured reference domains."""
    tavily_key = os.getenv("TAVILY_KEY")
    if not tavily_key:
        raise ValueError("Missing TAVILY_KEY for live search.")

    client = TavilyClient(api_key=tavily_key)
    queries = state.get("research_plan", {}).get("queries") or [state["query"]]
    query = queries[0]
    allowed_domains = sorted(_allowed_reference_domains(references))
    logger.debug(
        "Web searcher (%s): allowed domains=%s",
        agent_key,
        allowed_domains,
    )
    if not allowed_domains:
        logger.warning("Web searcher (%s): no configured domains for lane.", agent_key)
        return []

    sources: List[Source] = []
    seen_urls: set[str] = set()

    # Query each configured domain directly so every lane stays inside its source list.
    for domain in allowed_domains:
        domain_response = client.search(
            f"{query} site:{domain}",
            max_results=3,
            search_depth="advanced",
        )
        for item in domain_response.get("results", []):
            raw_notes = (item.get("content") or "").strip()
            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if not _url_matches_allowed_domains(url, {domain}):
                logger.debug(
                    "Web searcher (%s): dropped out-of-domain URL %s for domain=%s",
                    agent_key,
                    url,
                    domain,
                )
                continue
            seen_urls.add(url)
            sources.append(
                Source(
                    id=_source_id_for_lane(agent_key, len(sources) + 1),
                    title=(item.get("title") or "Untitled").strip(),
                    url=url,
                    notes=_normalize_source_notes(raw_notes),
                    content_excerpt=raw_notes or None,
                )
            )
            logger.debug(
                "Web searcher (%s): selected source=%s url=%s",
                agent_key,
                item.get("title"),
                url,
            )
            # Keep at most one item per configured domain.
            break

    if not sources:
        combined_query = _build_biased_query(query, references)
        logger.info("Web searcher (%s): no per-domain hits, trying combined query.", agent_key)
        response = client.search(
            combined_query,
            max_results=max(len(allowed_domains) * 3, 3),
            search_depth="advanced",
        )
        for item in response.get("results", []):
            raw_notes = (item.get("content") or "").strip()
            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if not _url_matches_allowed_domains(url, set(allowed_domains)):
                continue
            seen_urls.add(url)
            sources.append(
                Source(
                    id=_source_id_for_lane(agent_key, len(sources) + 1),
                    title=(item.get("title") or "Untitled").strip(),
                    url=url,
                    notes=_normalize_source_notes(raw_notes),
                    content_excerpt=raw_notes or None,
                )
            )
            if len(sources) >= len(allowed_domains):
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
