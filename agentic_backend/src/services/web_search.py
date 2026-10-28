"""Allow-listed Brave search.

This shared boundary names no agent. Callers supply a :class:`SourcePolicy`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from collections.abc import Sequence
from typing import Annotated
from urllib.parse import urlparse

import httpx
from pydantic import AfterValidator, BaseModel, ValidationError

from models import Candidate, SourcePolicy
from shared.errors import SearchUnavailableError
from shared.tracing import start_span

logger = logging.getLogger(__name__)
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_TIMEOUT_SECONDS = 10.0
BRAVE_RESULTS_PER_QUERY = 10
BRAVE_MAX_QUERY_CHARS = 400
BRAVE_MAX_QUERY_WORDS = 50
QUERY_TRIM_CHARS = 140
QUERY_TRIM_WORDS = 20
# A Brave text field arrives with its ends trimmed.
StripText = Annotated[str, AfterValidator(str.strip)]


# Search: Brave, behind the allow-list.
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


class BraveResult(BaseModel):
    """The two fields of one Brave web result that the search reads."""

    url: StripText = ""
    title: StripText = ""


class BraveWeb(BaseModel):
    """The `web` section of Brave's body."""

    results: list[BraveResult] = []


class BraveResponse(BaseModel):
    """Brave's search body; the rest of its fields are ignored."""

    web: BraveWeb = BraveWeb()


def describe_failure(error: BaseException) -> str:
    """Name why a request failed: its HTTP status, "timeout", or its exception class.

    Never the error's text: it can carry a URL or a header.
    """
    if isinstance(error, httpx.HTTPStatusError):
        return str(error.response.status_code)
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    return type(error).__name__


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
    try:
        payload = BraveResponse.model_validate_json(response.content)
    except ValidationError as exc:
        raise SearchUnavailableError("Brave returned an unexpected shape.") from exc
    candidates: list[Candidate] = []
    for item in payload.web.results:
        url = item.url
        if not url:
            logger.debug("Skipped Brave result with no usable url: %r", item)
            continue
        domain = allowed_domain(url, policy)
        if domain is None:
            logger.debug("Dropped out-of-allowlist URL: %s", url)
            continue
        title = item.title or "Untitled"
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


async def search_allowlisted(query: str, policy: SourcePolicy) -> list[Candidate]:
    """Run exactly one Brave request per policy batch and merge results.

    One `brave_search` span per call: what each batch returned after the
    allow-list gate, how many failed, and the domains searched, which for a
    forecaster search name the forecaster (brainstorm 2026Oct13 Q9).
    """
    brave_key = os.getenv("BRAVE_SEARCH_KEY")
    if not brave_key:
        raise SearchUnavailableError("Missing BRAVE_SEARCH_KEY for live search.")
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": brave_key,
    }
    with start_span("brave_search") as span:
        async with httpx.AsyncClient(headers=headers) as client:
            results = await asyncio.gather(
                *(
                    _brave_batch(client, query, batch, policy)
                    for batch in policy.batches
                ),
                return_exceptions=True,
            )
        batches: list[list[Candidate]] = []
        failures: list[str] = []
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                # Preserve cancellation: the request was aborted mid-search, and a
                # cancelled batch must not be swallowed as a mere "batch failed".
                raise result
            if isinstance(result, BaseException):
                logger.warning("Brave batch failed: %s", result)
                failures.append(describe_failure(result))
            else:
                batches.append(result)
        span.set_attributes(
            {
                "search.domains": sorted(policy.allowed_domains),
                "search.batches": len(policy.batches),
                "search.failed_batches": len(policy.batches) - len(batches),
                "search.failures": failures,
                "search.results_per_batch": [len(batch) for batch in batches],
            }
        )
        if not batches:
            raise SearchUnavailableError("Every Brave request failed for this run.")
        merged = merge_candidates(batches, policy)
        span.set_attribute("search.candidates", len(merged))
        return merged
