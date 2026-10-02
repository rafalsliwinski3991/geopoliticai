"""Graph-running helpers shared by the expert, deep expert, forecaster, reporter, and e2e evals."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from models import Candidate, Source, SourcePolicy

# The node imports both functions by name, so they are patched where it looks them up.
SEARCH_NODE_MODULE = "agents.expert.nodes.search_and_fetch"
# The deep expert's tools import the same two names; patched the same way.
DEEP_TOOLS_MODULE = "agents.deep_expert.tools"
# The forecaster's tools import all three names; patched the same way.
FORECASTER_TOOLS_MODULE = "agents.deep_forecaster.tools"


def load_sources(raw: Sequence[dict[str, Any]]) -> list[Source]:
    """Build recorded sources from dataset JSON; `author` is optional."""
    return [
        Source(
            title=item["title"],
            url=item["url"],
            text=item["text"],
            author=item.get("author", ""),
        )
        for item in raw
    ]


@contextmanager
def recorded_sources(current: Callable[[], list[Source] | None]) -> Iterator[None]:
    """Replace the expert's, the deep expert's, and the deep forecaster's live retrieval with recorded sources.

    `current` is read on every call, so e2e can change sources between turns.
    Every search returns the whole recorded set (brainstorm Q5b), so the deep
    eval measures synthesis and the grader loop, not search strategy.
    Reaching either agent with no recorded sources is an error: evals never call Brave.
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
        # Only what was asked for: the deep expert reads one URL at a time and
        # takes the first source back. The expert asks for every recorded URL,
        # so its result is unchanged.
        wanted = {candidate.url for candidate in candidates}
        return [source for source in sources() if source.url in wanted]

    async def watch_video(*_: object) -> str:
        raise RuntimeError("Evals never call Gemini's video reading.")

    with (
        patch(f"{SEARCH_NODE_MODULE}.search_allowlisted", search_allowlisted),
        patch(f"{SEARCH_NODE_MODULE}.fetch_sources", fetch_sources),
        patch(f"{DEEP_TOOLS_MODULE}.search_allowlisted", search_allowlisted),
        patch(f"{DEEP_TOOLS_MODULE}.fetch_sources", fetch_sources),
        patch(f"{FORECASTER_TOOLS_MODULE}.search_allowlisted", search_allowlisted),
        patch(f"{FORECASTER_TOOLS_MODULE}.fetch_sources", fetch_sources),
        patch(f"{FORECASTER_TOOLS_MODULE}.watch_video", watch_video),
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
