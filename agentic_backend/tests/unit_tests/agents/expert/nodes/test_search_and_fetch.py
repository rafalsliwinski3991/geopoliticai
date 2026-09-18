import importlib
from typing import Any

import pytest

from models import Candidate, NoSourcesError, Source

node_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
_STATE = {"query": "x", "sources": [], "answer": ""}


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
