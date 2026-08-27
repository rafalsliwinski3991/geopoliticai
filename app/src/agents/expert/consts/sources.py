"""The expert agent's editorial policy: which sources, and how many."""

from __future__ import annotations

from models import SourcePolicy

ALLOWED_DOMAINS: tuple[str, ...] = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "npr.org",
    "aljazeera.com",
    "dw.com",
    "france24.com",
    "axios.com",
    "politico.com",
    "csmonitor.com",
    "bloomberg.com",
    "ft.com",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "wsj.com",
    "economist.com",
    "vox.com",
    "thenation.com",
    "motherjones.com",
    "nationalreview.com",
    "thedispatch.com",
    "washingtonexaminer.com",
    "reason.com",
    "foxnews.com",
    "brookings.edu",
    "aei.org",
    "hoover.org",
)

SEARCH_BATCHES: tuple[tuple[str, ...], ...] = (
    (
        "reuters.com",
        "bbc.com",
        "theguardian.com",
        "wsj.com",
        "npr.org",
        "nationalreview.com",
        "politico.com",
        "aljazeera.com",
        "brookings.edu",
        "vox.com",
    ),
    (
        "apnews.com",
        "bloomberg.com",
        "ft.com",
        "washingtonpost.com",
        "foxnews.com",
        "dw.com",
        "axios.com",
        "aei.org",
        "thenation.com",
    ),
    (
        "economist.com",
        "nytimes.com",
        "thedispatch.com",
        "csmonitor.com",
        "france24.com",
        "washingtonexaminer.com",
        "reason.com",
        "hoover.org",
        "motherjones.com",
    ),
)

HARD_PAYWALLED_DOMAINS: frozenset[str] = frozenset(
    {
        "wsj.com",
        "ft.com",
        "economist.com",
        "nytimes.com",
        "washingtonpost.com",
        "bloomberg.com",
    }
)

EXPERT_SOURCES = SourcePolicy(
    allowed_domains=ALLOWED_DOMAINS,
    batches=SEARCH_BATCHES,
    deferred_domains=HARD_PAYWALLED_DOMAINS,
    max_per_domain=2,
    min_source_chars=500,
    max_source_chars=20_000,
)
