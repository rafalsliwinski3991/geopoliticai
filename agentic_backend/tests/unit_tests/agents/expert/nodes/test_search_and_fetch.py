import importlib
from typing import Any

import pytest

from models import Candidate, Source
from shared.errors import NoSourcesError

node_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
_STATE = {"query": "x", "search_query": "x", "sources": [], "answer": ""}


@pytest.mark.anyio
async def test_no_candidates_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    async def empty(query: str, policy: Any) -> list[Candidate]:
        return []

    monkeypatch.setattr(node_module, "search_allowlisted", empty)
    # Act + Assert
    with pytest.raises(NoSourcesError):
        await node_module.search_and_fetch(_STATE)


@pytest.mark.anyio
async def test_no_fetched_sources_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("t", "https://reuters.com/x", "reuters.com")]

    async def empty(candidates: list[Candidate], policy: Any) -> list[Source]:
        return []

    monkeypatch.setattr(node_module, "search_allowlisted", candidates)
    monkeypatch.setattr(node_module, "fetch_sources", empty)
    # Act + Assert
    with pytest.raises(NoSourcesError):
        await node_module.search_and_fetch(_STATE)


@pytest.mark.anyio
async def test_sources_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("t", "https://reuters.com/x", "reuters.com")] * 20

    async def sources(candidates: list[Candidate], policy: Any) -> list[Source]:
        return [Source(str(i), f"https://reuters.com/{i}", "body") for i in range(20)]

    monkeypatch.setattr(node_module, "search_allowlisted", candidates)
    monkeypatch.setattr(node_module, "fetch_sources", sources)
    # Act
    result = await node_module.search_and_fetch(_STATE)
    # Assert
    assert len(result["sources"]) == node_module.RETRIEVAL.keep_sources


@pytest.mark.anyio
async def test_search_and_fetch_queries_brave_with_search_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The allow-listed outlets publish in English, so a Polish question is searched in English."""
    # Arrange
    searched: list[str] = []

    async def candidates(query: str, policy: Any) -> list[Candidate]:
        searched.append(query)
        return [Candidate("t", "https://reuters.com/x", "reuters.com")]

    async def sources(candidates: list[Candidate], policy: Any) -> list[Source]:
        return [Source("t", "https://reuters.com/x", "body")]

    monkeypatch.setattr(node_module, "search_allowlisted", candidates)
    monkeypatch.setattr(node_module, "fetch_sources", sources)
    state = {
        "query": "Czym jest Artykuł 5 NATO?",
        "search_query": "What is NATO Article 5?",
        "sources": [],
        "answer": "",
    }

    # Act
    await node_module.search_and_fetch(state)

    # Assert
    assert searched == ["What is NATO Article 5?"]
