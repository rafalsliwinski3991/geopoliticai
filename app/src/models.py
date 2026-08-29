"""Shared data structures for every agent in this repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


class PipelineError(RuntimeError):
    """A failure the client must see, never a degraded answer.

    `status` is the HTTP code a delivery layer reports for this failure.
    It lives on the class so adding an error type cannot leave a lookup
    table behind.
    """

    status: ClassVar[int] = 500


class SearchUnavailableError(PipelineError):
    """Every Brave request attempted for this run failed."""

    status: ClassVar[int] = 503


class NoSourcesError(PipelineError):
    """No allow-listed page survived search, fetch, and extraction."""

    status: ClassVar[int] = 422


class LLMInvocationError(PipelineError):
    """The model call failed or returned nothing usable."""

    status: ClassVar[int] = 502


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
