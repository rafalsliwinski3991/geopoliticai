"""Allow-listed search, page fetch, and article extraction.

This shared boundary names no agent. Callers supply a :class:`SourcePolicy`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from collections.abc import Sequence
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from models import Candidate, SearchUnavailableError, Source, SourcePolicy

logger = logging.getLogger(__name__)
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_TIMEOUT_SECONDS = 10.0
BRAVE_RESULTS_PER_QUERY = 10
BRAVE_MAX_QUERY_CHARS = 400
BRAVE_MAX_QUERY_WORDS = 50
FETCH_TIMEOUT_SECONDS = 5.0
FETCH_CONCURRENCY = 8
QUERY_TRIM_CHARS = 140
QUERY_TRIM_WORDS = 20
MAX_REDIRECTS = 3
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _normalize_domain(url: str) -> str:
    """Return the lowercase host of a URL-like string without ``www.``."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path.split("/")[0]).lower().strip()
    return host[4:] if host.startswith("www.") else host


def allowed_domain(url: str, policy: SourcePolicy) -> str | None:
    """Return the allow-list entry this URL belongs to, or ``None``."""
    host = _normalize_domain(url)
    if not host:
        return None
    for allowed in policy.allowed_domains:
        if host == allowed or host.endswith(f".{allowed}"):
            return allowed
    return None


def _trim_query(query: str) -> str:
    """Trim a query to leave room for a Brave site filter."""
    words = query.split()[:QUERY_TRIM_WORDS]
    while words and len(" ".join(words)) > QUERY_TRIM_CHARS:
        words.pop()
    return " ".join(words)


def build_batch_query(query: str, domains: Sequence[str]) -> str:
    """Build a site-filtered query inside Brave's documented limits."""
    head = _trim_query(query)
    if not head:
        raise ValueError("Query is empty after trimming.")
    kept = list(domains)
    while kept:
        site_filter = " OR ".join(f"site:{domain}" for domain in kept)
        candidate = f"{head} ({site_filter})"
        if (
            len(candidate) <= BRAVE_MAX_QUERY_CHARS
            and len(candidate.split()) <= BRAVE_MAX_QUERY_WORDS
        ):
            return candidate
        logger.warning("Brave query over budget; dropping domain=%s", kept[-1])
        kept.pop()
    raise ValueError("Query too long to combine with any site filter.")


async def _brave_batch(
    client: httpx.AsyncClient, query: str, domains: Sequence[str], policy: SourcePolicy
) -> list[Candidate]:
    """Run one batched Brave query and return hard-gated results."""
    response = await client.get(
        BRAVE_SEARCH_URL,
        params={
            "q": build_batch_query(query, domains),
            "count": BRAVE_RESULTS_PER_QUERY,
        },
        timeout=BRAVE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    web = payload.get("web", {}) if isinstance(payload, dict) else {}
    results = web.get("results", []) if isinstance(web, dict) else []
    candidates: list[Candidate] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url")
        url = raw_url.strip() if isinstance(raw_url, str) else ""
        if not url:
            logger.debug("Skipped Brave result with no usable url: %r", item)
            continue
        domain = allowed_domain(url, policy)
        if domain is None:
            logger.debug("Dropped out-of-allowlist URL: %s", url)
            continue
        raw_title = item.get("title")
        title = (
            raw_title.strip()
            if isinstance(raw_title, str) and raw_title.strip()
            else "Untitled"
        )
        candidates.append(Candidate(title=title, url=url, domain=domain))
    return candidates


def merge_candidates(
    batches: Sequence[Sequence[Candidate]], policy: SourcePolicy
) -> list[Candidate]:
    """Interleave batches by rank, dedupe URLs, cap domains, and defer paywalls."""
    merged: list[Candidate] = []
    seen_urls: set[str] = set()
    per_domain: Counter[str] = Counter()
    depth = max((len(batch) for batch in batches), default=0)
    for rank in range(depth):
        for batch in batches:
            if rank >= len(batch):
                continue
            candidate = batch[rank]
            if (
                candidate.url in seen_urls
                or per_domain[candidate.domain] >= policy.max_per_domain
            ):
                continue
            seen_urls.add(candidate.url)
            per_domain[candidate.domain] += 1
            merged.append(candidate)
    merged.sort(key=lambda item: item.domain in policy.deferred_domains)
    return merged


async def _fetch_and_extract(
    client: httpx.AsyncClient, candidate: Candidate, policy: SourcePolicy
) -> Source | None:
    """Fetch and extract one page, dropping content-specific failures."""
    url = candidate.url
    for redirect in range(MAX_REDIRECTS + 1):
        if allowed_domain(url, policy) is None:
            logger.info("Rejected off-list fetch URL=%s", url)
            return None
        try:
            response = await client.get(
                url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            logger.info("Fetch failed url=%s: %s", url, exc)
            return None
        if response.is_redirect:
            location = response.headers.get("location")
            if not location or redirect >= MAX_REDIRECTS:
                logger.info("Redirect limit reached url=%s", url)
                return None
            next_url = urljoin(url, location)
            if allowed_domain(next_url, policy) is None:
                logger.info("Rejected off-list redirect %s -> %s", url, next_url)
                return None
            url = next_url
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("Fetch failed url=%s: %s", url, exc)
            return None
        try:
            if "html" not in response.headers.get("content-type", "").lower():
                return None
            body = response.text
            text = await _extract_text(body)
            if not text or len(text) < policy.min_source_chars:
                return None
            return Source(
                title=candidate.title, url=url, text=text[: policy.max_source_chars]
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not abort the batch
            logger.info("Extraction failed url=%s: %s", url, exc)
            return None
    return None


def _extract_sync(body: str) -> str | None:
    """Extract article text in a worker thread."""
    return trafilatura.extract(
        body, include_comments=False, include_tables=False, favor_precision=True
    )


async def _extract_text(body: str) -> str | None:
    """Run the synchronous extractor without blocking the event loop."""
    return await asyncio.to_thread(_extract_sync, body)


async def search_allowlisted(query: str, policy: SourcePolicy) -> list[Candidate]:
    """Run exactly one Brave request per policy batch and merge results."""
    brave_key = os.getenv("BRAVE_SEARCH_KEY")
    if not brave_key:
        raise SearchUnavailableError("Missing BRAVE_SEARCH_KEY for live search.")
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": brave_key,
    }
    async with httpx.AsyncClient(headers=headers) as client:
        results = await asyncio.gather(
            *(_brave_batch(client, query, batch, policy) for batch in policy.batches),
            return_exceptions=True,
        )
    batches: list[list[Candidate]] = []
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            # Preserve cancellation: the request was aborted mid-search, and a
            # cancelled batch must not be swallowed as a mere "batch failed".
            raise result
        if isinstance(result, BaseException):
            logger.warning("Brave batch failed: %s", result)
        else:
            batches.append(result)
    if not batches:
        raise SearchUnavailableError("Every Brave request failed for this run.")
    return merge_candidates(batches, policy)


async def fetch_sources(
    candidates: Sequence[Candidate], policy: SourcePolicy
) -> list[Source]:
    """Fetch and extract candidates concurrently, bounding parallel fetches."""
    async with httpx.AsyncClient(headers=FETCH_HEADERS) as client:
        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def bounded(candidate: Candidate) -> Source | None:
            async with semaphore:
                return await _fetch_and_extract(client, candidate, policy)

        fetched = await asyncio.gather(
            *(bounded(candidate) for candidate in candidates)
        )
    return [source for source in fetched if source is not None]
