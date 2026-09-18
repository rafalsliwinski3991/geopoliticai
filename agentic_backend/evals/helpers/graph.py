"""Graph-running helpers shared by the expert, reporter, and e2e evals."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from models import Candidate, Source, SourcePolicy

# The node imports both functions by name, so they are patched where it looks them up.
SEARCH_NODE_MODULE = "agents.expert.nodes.search_and_fetch"


def load_sources(raw: Sequence[dict[str, Any]]) -> list[Source]:
    """Build recorded sources from dataset JSON."""
    return [
        Source(title=item["title"], url=item["url"], text=item["text"]) for item in raw
    ]


@contextmanager
def recorded_sources(current: Callable[[], list[Source] | None]) -> Iterator[None]:
    """Replace the expert's live retrieval with recorded sources.

    `current` is read on every call, so e2e can change sources between turns.
    Reaching the expert with no recorded sources is an error: evals never call Brave.
    """

    def sources() -> list[Source]:
        recorded = current()
        if recorded is None:
            raise RuntimeError(
                "The expert was called, but this example has no recorded sources."
            )
        return recorded

    async def search_allowlisted(query: str, policy: SourcePolicy) -> list[Candidate]:
        return [
            Candidate(title=source.title, url=source.url, domain="recorded")
            for source in sources()
        ]

    async def fetch_sources(
        candidates: Sequence[Candidate], policy: SourcePolicy
    ) -> list[Source]:
        return sources()

    with (
        patch(f"{SEARCH_NODE_MODULE}.search_allowlisted", search_allowlisted),
        patch(f"{SEARCH_NODE_MODULE}.fetch_sources", fetch_sources),
    ):
        yield


async def pending_pause(graph: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    """Return the value a paused thread waits on, or None (mirrors `api._pending_pause`)."""
    interrupts = (await graph.aget_state(config)).interrupts
    if not interrupts:
        return None
    value = interrupts[0].value
    if isinstance(value, dict):
        return value
    return {"outline": [], "notice": str(value)}
