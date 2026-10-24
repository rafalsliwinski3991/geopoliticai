"""Graph-running helpers shared by the evals: recorded pages, recorded messages, and paused threads."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, replace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

import search
from models import Candidate, Source, SourcePolicy

# The node imports both functions by name, so they are patched where it looks them up.
SEARCH_NODE_MODULE = "agents.expert.nodes.search_and_fetch"
# The deep expert's tools import the same two names; patched the same way.
DEEP_TOOLS_MODULE = "agents.deep_expert.tools"
# `research()` builds its `ResearchRun` by name here; patched where it looks it up.
DEEP_EXPERT_RESEARCH_MODULE = "agents.deep_expert.research"
# The two roles a dataset conversation may hold, and the message each becomes.
MESSAGE_TYPES: dict[str, type[HumanMessage] | type[AIMessage]] = {
    "user": HumanMessage,
    "assistant": AIMessage,
}


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


def load_messages(raw: Sequence[Mapping[str, str]]) -> list[AnyMessage]:
    """Build chat messages from dataset JSON: `{"role": "user" | "assistant", "content": str}`."""
    messages: list[AnyMessage] = []
    for item in raw:
        message_type = MESSAGE_TYPES.get(item["role"])
        if message_type is None:
            raise ValueError(
                f"unknown message role {item['role']!r}: use user or assistant"
            )
        messages.append(message_type(item["content"]))
    return messages


@contextmanager
def replay_sources(recorded: list[Source] | None) -> Iterator[None]:
    """Replace the expert's and the deep expert's live retrieval with a case's recorded pages.

    Every search returns the whole recorded set (brainstorm Q5b), so the deep
    eval measures synthesis and the grader loop, not search strategy.
    Reaching either agent with no recorded sources is an error: evals never call Brave.
    """

    def sources() -> list[Source]:
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

    with (
        patch(f"{SEARCH_NODE_MODULE}.search_allowlisted", search_allowlisted),
        patch(f"{SEARCH_NODE_MODULE}.fetch_sources", fetch_sources),
        patch(f"{DEEP_TOOLS_MODULE}.search_allowlisted", search_allowlisted),
        patch(f"{DEEP_TOOLS_MODULE}.fetch_sources", fetch_sources),
    ):
        yield


@contextmanager
def record_sources(pages: list[Source]) -> Iterator[None]:
    """Let the deep expert's live page reads run, keeping each page under the URL it cites.

    The live twin of `replay_sources` for the deep expert's tools: search is
    left alone, and every page its `fetch_sources` returns is appended to
    `pages` once, in the order read. The page is kept under the URL the model
    asked for, which is the one it cites, even when a redirect changed
    `source.url` (as `agents/deep_expert/tools.py` keys `run.sources`); kept
    under the redirect target, a correct citation would fail the link check.
    """

    async def fetch_and_keep(
        candidates: Sequence[Candidate], policy: SourcePolicy
    ) -> list[Source]:
        fetched = await search.fetch_sources(candidates, policy)
        # The deep tool reads one URL at a time and takes the first page back.
        if len(candidates) == 1 and fetched:
            page = replace(fetched[0], url=candidates[0].url)
            if page.url not in {kept.url for kept in pages}:
                pages.append(page)
        return fetched

    with patch(f"{DEEP_TOOLS_MODULE}.fetch_sources", fetch_and_keep):
        yield


@contextmanager
def record_verdicts(verdicts: list[str]) -> Iterator[None]:
    """Keep the grader's verdicts of the deep run inside the block, in order.

    `research()` builds its `ResearchRun` itself and returns only the answer;
    the run is built with the caller's list as its `verdicts`.
    """
    from agents.deep_expert.state import ResearchRun

    def build_run(*args: Any, **kwargs: Any) -> ResearchRun:
        run = ResearchRun(*args, **kwargs)
        run.verdicts = verdicts
        return run

    with patch(f"{DEEP_EXPERT_RESEARCH_MODULE}.ResearchRun", build_run):
        yield


def dump_sources(sources: Sequence[Source]) -> list[dict[str, str]]:
    """Write sources as dataset JSON, the shape `load_sources` reads."""
    return [asdict(source) for source in sources]


async def pending_pause(graph: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    """Return the value a paused thread waits on, or None (mirrors `api._pending_pause`)."""
    interrupts = (await graph.aget_state(config)).interrupts
    if not interrupts:
        return None
    value = interrupts[0].value
    if isinstance(value, dict):
        return value
    return {"outline": [], "notice": str(value)}
