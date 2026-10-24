"""Unit tests for `agents.orchestrator.nodes.deep_expert`."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agents.orchestrator.state import OrchestratorState
from frames import NoticeEvent

node_module: Any = importlib.import_module("agents.orchestrator.nodes.deep_expert")

DEEP_ANSWER = "Deep answer [a](https://reuters.com/x)."


@pytest.mark.anyio
async def test_the_node_receives_the_query_and_writes_exactly_one_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    received: dict[str, Any] = {}
    events: list[object] = []

    async def fake_research(query: str, writer: Any) -> str:
        received["query"] = query
        received["writer"] = writer
        return DEEP_ANSWER

    # Pytest restores the production `research` after the test; the previous
    # manual `try/finally` left a raising stub installed for every later test
    # in the process (review thread, #130 c4133685799).
    monkeypatch.setattr(node_module, "research", fake_research)
    state: OrchestratorState = {
        "messages": [],
        "standalone_query": "the rewritten query",
    }

    # Act
    result = await node_module.deep_expert(state, events.append)

    # Assert
    assert received["query"] == "the rewritten query"
    assert received["writer"] is not None
    assert events == [NoticeEvent(text=DEEP_ANSWER)]
    assert result == {"messages": [AIMessage(DEEP_ANSWER)]}
