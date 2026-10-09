"""Allow-listed search, page fetch, and article extraction.

This shared boundary names no agent. Callers supply a :class:`SourcePolicy`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter
from collections.abc import Sequence
from html.parser import HTMLParser
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

# A byline is what the page declares as its author (brainstorm 2026Sep30 Q16):
# the `author` of any JSON-LD (Schema.org linked-data) object on the page, else
# `<meta name="author">`. The object's `@type` is not checked: the sources come
# from an expert-written allow-list, and a `Person`-typed object's own `author`
# field is still the page's declared byline. A JSON-LD `Person` object without
# an `author` field contributes nothing.
MAX_AUTHOR_CHARS = 200
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
            text, author = await _extract_page(body)
            if not text or len(text) < policy.min_source_chars:
                return None
            return Source(
                title=candidate.title,
                url=url,
                text=text[: policy.max_source_chars],
                author=author,
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not abort the batch
            logger.info("Extraction failed url=%s: %s", url, exc)
            return None
    return None


def _extract_page_sync(body: str) -> tuple[str | None, str]:
    """Extract the article text and the page's declared byline in one worker.

    `asyncio.to_thread` costs one hop into a worker, so the byline read shares
    that hop with the text extraction (review thread, #139): no second full
    parse pass runs as a second hop on a body the fetch already read.
    """
    text = trafilatura.extract(  # noqa: FURB101 - see the worker-thread docstring
        body, include_comments=False, include_tables=False, favor_precision=True
    )
    return text, _byline_sync(body)


async def _extract_page(body: str) -> tuple[str | None, str]:
    """Run the synchronous extractor without blocking the event loop."""
    return await asyncio.to_thread(_extract_page_sync, body)


class _BylineParser(HTMLParser):
    """Collect a page's `<meta name="author">` values and JSON-LD blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.meta_authors: list[str] = []
        self.json_ld: list[str] = []
        self._in_json_ld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "meta" and values.get("name", "").lower() == "author":
            self.meta_authors.append(values.get("content", ""))
        elif (
            tag == "script" and values.get("type", "").lower() == "application/ld+json"
        ):
            self._in_json_ld = True
            self.json_ld.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self.json_ld[-1] += data


def _json_ld_authors(node: object) -> list[str]:
    """Return the author names of every author-bearing object in a JSON-LD tree.

    `@type` is not consulted (review thread, #139): the fetched pages come from
    an expert-written domain list, so any object that declares `author` is one
    of the page's declared authors, and both a list-valued `@type` and a
    bare-string `author` are handled.
    """
    if isinstance(node, list):
        return [name for item in node for name in _json_ld_authors(item)]
    if not isinstance(node, dict):
        return []
    names = _json_ld_authors(node.get("@graph", []))
    authors = node.get("author")
    for author in authors if isinstance(authors, list) else [authors]:
        name = author.get("name") if isinstance(author, dict) else author
        if isinstance(name, str):
            names.append(name)
    return names


def _byline_sync(body: str) -> str:
    """Return the page's own byline, or "" (worker thread).

    A byline is optional: a malformed page or JSON-LD block must never drop a
    page the article extraction accepted, so any failure returns "".
    """
    try:
        parser = _BylineParser()
        parser.feed(body)
        parser.close()
        names: list[str] = []
        for block in parser.json_ld:
            try:
                names += _json_ld_authors(json.loads(block))
            except ValueError:
                continue
        names = names or parser.meta_authors
        cleaned = (" ".join(name.split()) for name in names)
        byline = ", ".join(dict.fromkeys(name for name in cleaned if name))
    except Exception:  # noqa: BLE001 - an optional byline never costs a source
        return ""
    return byline[:MAX_AUTHOR_CHARS]


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
