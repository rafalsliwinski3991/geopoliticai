"""The expert agent's editorial policy: which sources, and how many."""

from __future__ import annotations

from models import SourcePolicy

ALLOWED_DOMAINS: tuple[str, ...] = (
    "bbc.com",
    "npr.org",
    "aljazeera.com",
    "dw.com",
    "csmonitor.com",
    "bloomberg.com",
    "theguardian.com",
    "vox.com",
    "thenation.com",
    "motherjones.com",
    "thedispatch.com",
    "reason.com",
    "foxnews.com",
    "brookings.edu",
    "aei.org",
    "hoover.org",
    "carnegieendowment.org",
    "csis.org",
    "sipri.org",
    "ecfr.eu",
    "osw.waw.pl",
    "cfr.org",
    "atlanticcouncil.org",
    "cnas.org",
    "swp-berlin.org",
    "warontherocks.com",
)

SEARCH_BATCHES: tuple[tuple[str, ...], ...] = (
    (
        "bbc.com",
        "theguardian.com",
        "npr.org",
        "aljazeera.com",
        "brookings.edu",
        "csis.org",
        "carnegieendowment.org",
        "thedispatch.com",
        "sipri.org",
    ),
    (
        "dw.com",
        "bloomberg.com",
        "foxnews.com",
        "aei.org",
        "vox.com",
        "cfr.org",
        "ecfr.eu",
        "atlanticcouncil.org",
        "osw.waw.pl",
    ),
    (
        "csmonitor.com",
        "reason.com",
        "hoover.org",
        "thenation.com",
        "motherjones.com",
        "cnas.org",
        "swp-berlin.org",
        "warontherocks.com",
    ),
)

HARD_PAYWALLED_DOMAINS: frozenset[str] = frozenset({"bloomberg.com"})

EXPERT_SOURCES = SourcePolicy(
    allowed_domains=ALLOWED_DOMAINS,
    batches=SEARCH_BATCHES,
    deferred_domains=HARD_PAYWALLED_DOMAINS,
    max_per_domain=2,
    min_source_chars=500,
    max_source_chars=20_000,
)
