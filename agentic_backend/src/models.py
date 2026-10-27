"""Shared data structures for every agent in this repository."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict


class OutlinePause(BaseModel):
    """The outline a paused report waits on: the gate's `interrupt()` payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Deliberately no "kind" key: `result` frames use it for report/answer, and
    # the pause frame built from this model is read by the same client handler.
    outline: list[str]
    notice: str
    revisions_used: int
    revisions_allowed: int


@dataclass(frozen=True)
class Candidate:
    """An allow-listed search result, before its page is fetched."""

    title: str
    url: str
    domain: str


@dataclass(frozen=True)
class Source:
    """An allow-listed page whose article text was fetched and extracted.

    `author` is the page's own byline as its metadata states it, or "" when
    it states none. Only the forecaster reads it (brainstorm 2026Sep30 Q16): a
    name is credited only when the page itself carries it, never because a
    search for that name found the page. It has a default so every existing
    construction, and every checkpoint written before it, still loads.
    """

    title: str
    url: str
    text: str
    author: str = ""


@dataclass(frozen=True)
class SourcePolicy:
    """Which sources an agent accepts, and how many."""

    allowed_domains: tuple[str, ...]
    batches: tuple[tuple[str, ...], ...]
    deferred_domains: frozenset[str]
    max_per_domain: int
    min_source_chars: int
    max_source_chars: int
