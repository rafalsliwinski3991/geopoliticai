"""Shared data structures for every agent in this repository."""

from __future__ import annotations

from dataclasses import dataclass


class PipelineError(RuntimeError):
    """A failure the client must see, never a degraded answer."""


class SearchUnavailableError(PipelineError):
    """Every Brave request attempted for this run failed."""


class NoSourcesError(PipelineError):
    """No allow-listed page survived search, fetch, and extraction."""


@dataclass(frozen=True)
class Candidate:
    """An allow-listed search result, before its page is fetched."""

    title: str
    url: str
    domain: str


@dataclass(frozen=True)
class Source:
    """An allow-listed page whose article text was fetched and extracted."""

    title: str
    url: str
    text: str


@dataclass(frozen=True)
class SourcePolicy:
    """Which sources an agent accepts, and how many."""

    allowed_domains: tuple[str, ...]
    batches: tuple[tuple[str, ...], ...]
    deferred_domains: frozenset[str]
    max_per_domain: int
    min_source_chars: int
    max_source_chars: int
